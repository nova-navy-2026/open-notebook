"""Internet reachability probe.

This deployment normally runs on a closed LAN with no route to the public
internet, so features that depend on it (web research via Tavily, ingesting a
source from a URL) cannot work. Rather than hard-disabling them, we probe for
connectivity and let the UI enable those features only when the internet is
actually reachable.

Design notes:

* **Cached.** A probe is at most one HTTP request per ``INTERNET_CHECK_TTL``
  seconds (default 300). Callers hit the cache, not the network.
* **Short timeout.** On an air-gapped network a connection attempt can hang
  until DNS/TCP gives up, so the timeout is deliberately small (default 3s).
* **Fail-closed.** Any error — DNS failure, timeout, TLS problem — is treated
  as "offline". A feature that needs the internet should stay off unless we
  positively confirmed connectivity.
* **Any HTTP response counts.** A 401/403 from the probe target still proves
  packets are flowing, so we only care that a response came back at all.

Environment:
    INTERNET_PROBE_URLS   comma-separated URLs to try (first success wins).
    INTERNET_PROBE_TIMEOUT seconds per attempt (default 3).
    INTERNET_CHECK_TTL    seconds to cache the result (default 300).
    FORCE_OFFLINE=1       skip probing, always report offline (useful to
                          pre-configure a closed deployment, or to test).
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import List, Optional, Tuple

import httpx
from loguru import logger

# Small, well-known endpoints that return quickly. The first to answer wins.
_DEFAULT_PROBE_URLS = (
    "https://www.gstatic.com/generate_204",
    "https://1.1.1.1",
)

_cache_lock = asyncio.Lock()
# (checked_at_monotonic, online)
_cache: Optional[Tuple[float, bool]] = None


def force_offline() -> bool:
    """True when the operator pinned this deployment to offline mode."""
    flag = (os.environ.get("FORCE_OFFLINE", "") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _probe_urls() -> List[str]:
    raw = (os.environ.get("INTERNET_PROBE_URLS", "") or "").strip()
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return list(_DEFAULT_PROBE_URLS)


def _timeout() -> float:
    try:
        return float(os.environ.get("INTERNET_PROBE_TIMEOUT", "3"))
    except ValueError:
        return 3.0


def _ttl() -> float:
    try:
        return float(os.environ.get("INTERNET_CHECK_TTL", "300"))
    except ValueError:
        return 300.0


async def _probe_once() -> bool:
    """Single uncached probe. True when any target answers."""
    timeout = _timeout()
    for url in _probe_urls():
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False
            ) as client:
                await client.head(url)
            # Any response at all proves reachability (even 4xx/5xx).
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug(
                f"[connectivity] probe {url} failed ({type(e).__name__}): {e or repr(e)}"
            )
    return False


async def internet_available(force: bool = False) -> bool:
    """Return True when the public internet appears reachable.

    Result is cached for ``INTERNET_CHECK_TTL`` seconds. Pass ``force=True`` to
    bypass the cache (used by the manual "re-check" action).
    """
    global _cache

    if force_offline():
        return False

    now = time.monotonic()
    if not force and _cache is not None:
        checked_at, online = _cache
        if now - checked_at < _ttl():
            return online

    async with _cache_lock:
        # Another coroutine may have refreshed while we waited.
        if not force and _cache is not None:
            checked_at, online = _cache
            if time.monotonic() - checked_at < _ttl():
                return online

        online = await _probe_once()
        _cache = (time.monotonic(), online)
        logger.info(f"[connectivity] internet reachable: {online}")
        return online


def cached_status() -> Optional[bool]:
    """Last known result without probing. None when never checked."""
    if force_offline():
        return False
    return _cache[1] if _cache else None


def reset_cache() -> None:
    """Clear the cached result (tests)."""
    global _cache
    _cache = None
