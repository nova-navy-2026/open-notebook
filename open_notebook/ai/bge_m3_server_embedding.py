"""HTTP adapter that routes bge-m3 embeddings to a warm embedding server.

The standard in-process ``transformers`` embedding provider reloads the model
weights from disk on every call, which adds several seconds of latency per
request. This adapter instead delegates embedding requests to a persistent
"warm" bge-m3 server (the one shipped with NOVA-Researcher, ``bge_m3_server.py``)
where the model is loaded once at startup, reducing per-call latency from
seconds to tens of milliseconds.

The server contract is::

    POST {base_url}/embed   {"texts": [...]}  ->  {"embeddings": [[...], ...]}

If the server is unreachable or returns an error, the adapter transparently
falls back to a provided fallback model (typically the standard in-process
transformers provider), so embeddings never fail outright because of the
optional server.
"""

import logging
import os
from typing import Any, Callable, List, Optional

import httpx

from esperanto.common_types import Model
from esperanto.providers.embedding.base import EmbeddingModel

logger = logging.getLogger(__name__)

DEFAULT_SERVER_URL = "http://localhost:4803"
DEFAULT_TIMEOUT = 120.0


class BgeM3ServerEmbeddingModel(EmbeddingModel):
    """Embedding model that delegates to a warm bge-m3 HTTP server.

    Implements the Esperanto :class:`EmbeddingModel` contract so it can be
    used anywhere the application expects an embedding model (e.g. the
    ``aembed`` calls in the embedding pipeline).
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        server_url: Optional[str] = None,
        timeout: Optional[float] = None,
        fallback_factory: Optional[Callable[[], EmbeddingModel]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model_name=model_name, **kwargs)

        resolved_url = (
            server_url
            or os.environ.get("BGE_M3_SERVER_URL")
            or DEFAULT_SERVER_URL
        )
        self.server_url = resolved_url.rstrip("/")

        env_timeout = os.environ.get("BGE_M3_TIMEOUT")
        if timeout is not None:
            self.timeout = float(timeout)
        elif env_timeout:
            self.timeout = float(env_timeout)
        else:
            self.timeout = DEFAULT_TIMEOUT

        self._fallback_factory = fallback_factory
        self._fallback_model: Optional[EmbeddingModel] = None

    # ------------------------------------------------------------------
    # Server-backed embedding
    # ------------------------------------------------------------------
    def _server_embed(self, texts: List[str]) -> List[List[float]]:
        url = f"{self.server_url}/embed"
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json={"texts": texts})
            response.raise_for_status()
            data = response.json()
        return data["embeddings"]

    async def _aserver_embed(self, texts: List[str]) -> List[List[float]]:
        url = f"{self.server_url}/embed"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json={"texts": texts})
            response.raise_for_status()
            data = response.json()
        return data["embeddings"]

    def _get_fallback(self) -> Optional[EmbeddingModel]:
        if self._fallback_model is None and self._fallback_factory is not None:
            try:
                self._fallback_model = self._fallback_factory()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Failed to build embedding fallback model: %s", exc)
                self._fallback_model = None
        return self._fallback_model

    # ------------------------------------------------------------------
    # EmbeddingModel interface
    # ------------------------------------------------------------------
    def embed(self, texts: List[str], **kwargs: Any) -> List[List[float]]:
        try:
            return self._server_embed(list(texts))
        except Exception as exc:
            logger.warning(
                "bge-m3 server embed failed (%s); falling back to in-process model.",
                exc,
            )
            fallback = self._get_fallback()
            if fallback is None:
                raise
            return fallback.embed(texts, **kwargs)

    async def aembed(self, texts: List[str], **kwargs: Any) -> List[List[float]]:
        try:
            return await self._aserver_embed(list(texts))
        except Exception as exc:
            logger.warning(
                "bge-m3 server aembed failed (%s); falling back to in-process model.",
                exc,
            )
            fallback = self._get_fallback()
            if fallback is None:
                raise
            return await fallback.aembed(texts, **kwargs)

    @property
    def provider(self) -> str:
        return "bge_m3_server"

    def _get_default_model(self) -> str:
        return "bge-m3"

    def _get_models(self) -> List[Model]:
        return [
            Model(
                id=self.get_model_name(),
                owned_by="BAAI",
                context_window=8192,
            )
        ]
