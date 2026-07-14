# Build stage
FROM python:3.12-slim-bookworm AS builder
ARG HTTP_PROXY=http://10.46.0.118:8080
ARG HTTPS_PROXY=http://10.46.0.118:8080
ARG NO_PROXY=localhost,127.0.0.1,surrealdb,nn-notebook-surrealdb,nova-researcher,nova-whisper,nova-sam3,nova-nomic,nova-rf-detr,nova-bge-m3,nova-clip,ollama,marinha-opensearch

ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTPS_PROXY
ENV NO_PROXY=$NO_PROXY
ENV http_proxy=$HTTP_PROXY
ENV https_proxy=$HTTPS_PROXY
ENV no_proxy=$NO_PROXY

RUN printf '%s\n' \
'Acquire::http::Proxy "http://10.46.0.118:8080";' \
'Acquire::https::Proxy "http://10.46.0.118:8080";' \
> /etc/apt/apt.conf.d/01proxy

COPY root-ca-ca.crt /usr/local/share/ca-certificates/
COPY marinha-root-ca.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates

# pip / uv / requests default to the certifi bundle, which lacks the corporate
# root CA — point them at the system store (updated above) so HTTPS through the
# MITM proxy validates during THIS build stage (uv sync, pip torch install).
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Install uv using the official method
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies required for building certain Python packages
# Add Node.js 20.x LTS for building frontend
# NOTE: gcc/g++/make removed - uv should download pre-built wheels. Add back if build fails.
# NOTE: gcc/g++/make required for some python dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set build optimization environment variables
ENV MAKEFLAGS="-j$(nproc)"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=0
ENV UV_LINK_MODE=copy

# Set the working directory in the container to /app
WORKDIR /app

# Copy dependency files and minimal package structure first for better layer caching
COPY pyproject.toml uv.lock ./
COPY open_notebook/__init__.py ./open_notebook/__init__.py

# Install dependencies with optimizations (this layer will be cached unless dependencies change)
RUN UV_COMPILE_BYTECODE=0 uv sync --frozen --no-dev

# Install the optional "transformers" embedding provider stack (CPU-only torch wheel).
# Needed so the local HuggingFace transformers embedding provider in esperanto works
# without bringing in a CUDA-sized torch. ~250 MB total.
RUN .venv/bin/pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        torch \
        transformers \
        sentence-transformers

# Pre-download tiktoken encoding so the app works offline (issue #264).
# /app/tiktoken-cache is intentionally outside /app/data/ so that volume mounts
# of /app/data (for user data persistence) do not hide the pre-baked encoding.
# config.py reads TIKTOKEN_CACHE_DIR from the environment to pick up this path.
ENV TIKTOKEN_CACHE_DIR=/app/tiktoken-cache
RUN mkdir -p /app/tiktoken-cache && \
    .venv/bin/python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

# Copy the rest of the application code
COPY . /app

# Install frontend dependencies and build
WORKDIR /app/frontend
ARG NPM_REGISTRY=https://registry.npmjs.org/
COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry ${NPM_REGISTRY}
RUN npm config set registry https://registry.npmjs.org/
RUN npm config set strict-ssl false
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Return to app root
WORKDIR /app

# Runtime stage
FROM python:3.12-slim-bookworm AS runtime
ARG HTTP_PROXY=http://10.46.0.118:8080
ARG HTTPS_PROXY=http://10.46.0.118:8080
ARG NO_PROXY=localhost,127.0.0.1,surrealdb,nn-notebook-surrealdb,nova-researcher,nova-whisper,nova-sam3,nova-nomic,nova-rf-detr,nova-bge-m3,nova-clip,ollama,marinha-opensearch

ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTPS_PROXY
ENV NO_PROXY=$NO_PROXY
ENV http_proxy=$HTTP_PROXY
ENV https_proxy=$HTTPS_PROXY
ENV no_proxy=$NO_PROXY

RUN printf '%s\n' \
'Acquire::http::Proxy "http://10.46.0.118:8080";' \
'Acquire::https::Proxy "http://10.46.0.118:8080";' \
> /etc/apt/apt.conf.d/01proxy

COPY root-ca-ca.crt /usr/local/share/ca-certificates/
COPY marinha-root-ca.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates
# Runtime Python HTTPS (LLM / HuggingFace / OpenSearch through the MITM proxy)
# also needs the corporate CA. This is a fresh base stage, so the builder's
# cert env does NOT carry over — set it again here.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
# Install only runtime system dependencies (no build tools)
# Add Node.js 20.x LTS for running frontend
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    ffmpeg \
    supervisor \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv using the official method
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the working directory in the container to /app
WORKDIR /app

# Copy the virtual environment from builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy the source code (the rest)
COPY . /app

# Copy pre-downloaded tiktoken encoding from builder (outside /data/ — volume-mount safe)
COPY --from=builder /app/tiktoken-cache /app/tiktoken-cache

# Ensure uv uses the existing venv without attempting network operations
ENV UV_NO_SYNC=1
ENV VIRTUAL_ENV=/app/.venv
# Point the app at the pre-baked tiktoken encoding (see open_notebook/config.py)
ENV TIKTOKEN_CACHE_DIR=/app/tiktoken-cache

# Bind Next.js to all interfaces (required for Docker networking and reverse proxies)
ENV HOSTNAME=0.0.0.0

# Copy built frontend from builder stage
COPY --from=builder /app/frontend/.next/standalone /app/frontend/
COPY --from=builder /app/frontend/.next/static /app/frontend/.next/static
COPY --from=builder /app/frontend/public /app/frontend/public
COPY --from=builder /app/frontend/start-server.js /app/frontend/start-server.js

# Expose ports for Frontend and API
EXPOSE 3675 5055

RUN mkdir -p /app/data

# Copy and make executable the wait-for-api script
# sed strips Windows CRLF line endings so bash can parse the shebang on Linux
COPY scripts/wait-for-api.sh /app/scripts/wait-for-api.sh
RUN sed -i 's/\r//' /app/scripts/wait-for-api.sh && chmod +x /app/scripts/wait-for-api.sh

# Copy supervisord configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create log directories
RUN mkdir -p /var/log/supervisor

# Runtime API URL Configuration
# The API_URL environment variable can be set at container runtime to configure
# where the frontend should connect to the API. This allows the same Docker image
# to work in different deployment scenarios without rebuilding.
#
# If not set, the system will auto-detect based on incoming requests.
# Set API_URL when using reverse proxies or custom domains.
#
# Example: docker run -e API_URL=https://your-domain.com/api ...

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
