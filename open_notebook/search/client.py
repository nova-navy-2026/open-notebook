"""OpenSearch client singleton.

Uses the synchronous opensearch-py client wrapped in asyncio.to_thread()
to avoid adding aiohttp as a dependency (the codebase uses httpx).

Supports remote clusters behind a reverse-proxy path prefix, e.g.:
    https://api.novasearch.org:443/opensearch_v3
"""

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from open_notebook.config import (
    OPENSEARCH_HOST,
    OPENSEARCH_PASSWORD,
    OPENSEARCH_PORT,
    OPENSEARCH_SCHEME,
    OPENSEARCH_URL_PREFIX,
    OPENSEARCH_USE_SSL,
    OPENSEARCH_USER,
    OPENSEARCH_VERIFY_CERTS,
)

_client: Optional[Any] = None
_client_lock = asyncio.Lock()


def _create_client() -> Any:
    """Create a synchronous OpenSearch client."""
    try:
        from opensearchpy import OpenSearch
    except ImportError:
        raise ImportError(
            "opensearch-py is required when SEARCH_BACKEND=opensearch. "
            "Install it with: pip install 'opensearch-py>=2.4.0'"
        )

    host_entry: Dict[str, Any] = {
        "host": OPENSEARCH_HOST,
        "port": OPENSEARCH_PORT,
    }
    if OPENSEARCH_URL_PREFIX:
        host_entry["url_prefix"] = OPENSEARCH_URL_PREFIX

    kwargs: Dict[str, Any] = {
        "hosts": [host_entry],
        "scheme": OPENSEARCH_SCHEME,
        "use_ssl": OPENSEARCH_USE_SSL,
        "verify_certs": OPENSEARCH_VERIFY_CERTS,
        "timeout": 30,
        "max_retries": 3,
        "retry_on_timeout": True,
    }

    if OPENSEARCH_USE_SSL:
        kwargs["ssl_show_warn"] = False

    if OPENSEARCH_USER and OPENSEARCH_PASSWORD:
        kwargs["http_auth"] = (OPENSEARCH_USER, OPENSEARCH_PASSWORD)

    prefix_part = f"/{OPENSEARCH_URL_PREFIX}" if OPENSEARCH_URL_PREFIX else ""
    logger.info(
        f"OpenSearch client → {OPENSEARCH_SCHEME}://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}"
        f"{prefix_part}"
    )

    return OpenSearch(**kwargs)


async def get_client() -> Any:
    """Get or create the OpenSearch client singleton (thread-safe)."""
    global _client
    if _client is not None:
        return _client

    async with _client_lock:
        if _client is not None:
            return _client
        _client = await asyncio.to_thread(_create_client)
        return _client


async def check_health() -> bool:
    """Check if OpenSearch is reachable and return True/False."""
    try:
        client = await get_client()
        info = await asyncio.to_thread(client.info)
        version = info.get("version", {}).get("number", "unknown")
        logger.debug(f"OpenSearch connected: v{version}")
        return True
    except Exception as e:
        logger.warning(f"OpenSearch health check failed: {e}")
        return False
