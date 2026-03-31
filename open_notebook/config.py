import os

# ROOT DATA FOLDER
DATA_FOLDER = "./data"

# LANGGRAPH CHECKPOINT FILE
sqlite_folder = f"{DATA_FOLDER}/sqlite-db"
os.makedirs(sqlite_folder, exist_ok=True)
LANGGRAPH_CHECKPOINT_FILE = f"{sqlite_folder}/checkpoints.sqlite"

# UPLOADS FOLDER (legacy — kept for backward compatibility during migration)
UPLOADS_FOLDER = f"{DATA_FOLDER}/uploads"
os.makedirs(UPLOADS_FOLDER, exist_ok=True)

# MAX UPLOAD FILE SIZE (in MB) — files larger than this are rejected
# Set to 0 to disable the limit
MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "50"))

# TIKTOKEN CACHE FOLDER
# Reads TIKTOKEN_CACHE_DIR from the environment so Docker can redirect the cache
# to a path outside /data/ (which is typically volume-mounted and would hide the
# pre-baked encoding baked into the image at build time).
TIKTOKEN_CACHE_DIR = os.environ.get("TIKTOKEN_CACHE_DIR", "").strip() or f"{DATA_FOLDER}/tiktoken-cache"
os.makedirs(TIKTOKEN_CACHE_DIR, exist_ok=True)

# ============================================================================
# SEARCH BACKEND — "surrealdb" (default) or "opensearch"
# ============================================================================
SEARCH_BACKEND = os.environ.get("SEARCH_BACKEND", "surrealdb").strip().lower()

# OpenSearch connection settings (only used when SEARCH_BACKEND=opensearch)
# Supports remote clusters behind a reverse-proxy path prefix.
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "localhost").strip()
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT", "9200"))
OPENSEARCH_SCHEME = os.environ.get("OPENSEARCH_SCHEME", "https").strip()
OPENSEARCH_URL_PREFIX = os.environ.get("OPENSEARCH_URL_PREFIX", "").strip().strip("/")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "").strip()
OPENSEARCH_PASSWORD = os.environ.get("OPENSEARCH_PASSWORD", "").strip()
OPENSEARCH_INDEX_PREFIX = os.environ.get("OPENSEARCH_INDEX_PREFIX", "open_notebook").strip()
OPENSEARCH_VERIFY_CERTS = os.environ.get(
    "OPENSEARCH_VERIFY_CERTS", "true"
).strip().lower() in ("true", "1", "yes")

# Derived: the actual index name used for all operations
OPENSEARCH_INDEX = OPENSEARCH_INDEX_PREFIX
# Derived: whether to use SSL (true when scheme is https)
OPENSEARCH_USE_SSL = OPENSEARCH_SCHEME == "https"
