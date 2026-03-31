"""
OpenSearch integration for Open Notebook.

Provides hybrid search (BM25 + vector k-NN), ANN indexing, filters, and facets
as an alternative to SurrealDB's built-in search functions.

Configuration:
    SEARCH_BACKEND=opensearch           # Enable OpenSearch (default: "surrealdb")
    OPENSEARCH_HOST=localhost            # Hostname of the OpenSearch cluster
    OPENSEARCH_PORT=9200                 # Port
    OPENSEARCH_SCHEME=https              # http or https
    OPENSEARCH_URL_PREFIX=               # URL prefix for reverse-proxied clusters
    OPENSEARCH_USER=                     # Basic auth username (optional)
    OPENSEARCH_PASSWORD=                 # Basic auth password (optional)
    OPENSEARCH_INDEX_PREFIX=open_notebook # Index name prefix

When SEARCH_BACKEND=surrealdb (default), no OpenSearch code runs.
If OpenSearch is enabled but goes down, searches gracefully degrade
back to SurrealDB.
"""

from open_notebook.config import SEARCH_BACKEND


def is_opensearch_enabled() -> bool:
    """Check if OpenSearch is configured as the search backend."""
    return SEARCH_BACKEND == "opensearch"
