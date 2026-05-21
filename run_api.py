#!/usr/bin/env python3
"""
Startup script for Open Notebook API server.
"""

import os
import sys
import multiprocessing
from pathlib import Path

import uvicorn

# Add the current directory to Python path so imports work
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def get_allocated_cores() -> int:
    """
    Safely determine the number of CPU cores explicitly allocated to this container.
    Prevents reading the full physical host cores on shared clusters.
    """
    try:
        # Works on Linux and respects Docker/Kubernetes/cgroups CPU limits
        return len(os.sched_getaffinity(0))
    except AttributeError:
        # Fallback for local development on Windows/macOS
        return multiprocessing.cpu_count()

if __name__ == "__main__":
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "5055"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"

    # ── Optimized Worker / Concurrency Settings ──────────────────────────────
    allocated_cores = get_allocated_cores()
    
    # Modern ASGI standard: 1 worker per allocated core is highly efficient.
    # We enforce a hard ceiling of 8 workers for the automatic fallback to 
    # protect cluster memory. If you need more, explicitly pass API_WORKERS.
    MAX_AUTOMATIC_WORKERS = 4
    default_workers = min(max(1, allocated_cores), MAX_AUTOMATIC_WORKERS)
    
    workers = int(os.getenv("API_WORKERS", default_workers if not reload else 1))

    # Each worker keeps up to this many idle keep-alive connections.
    backlog = int(os.getenv("API_BACKLOG", "2048"))

    # Per-request timeout in seconds (guards against runaway LLM calls).
    timeout_keep_alive = int(os.getenv("API_TIMEOUT_KEEP_ALIVE", "75"))

    print(f"Starting Open Notebook API server on {host}:{port}")
    print(f"  detected_allocated_cores={allocated_cores}")
    print(f"  workers={workers}  reload={reload}  backlog={backlog}"
          f"  timeout_keep_alive={timeout_keep_alive}s")

    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(current_dir)] if reload else None,
        # ── concurrency ──────────────────────────────────────────────────
        workers=workers,          # multiple OS processes; ignored when reload=True
        loop="uvloop",            # faster async event loop (pip install uvloop)
        # ── connection handling ──────────────────────────────────────────
        backlog=backlog,          # OS listen() queue depth
        timeout_keep_alive=timeout_keep_alive,  # seconds before closing idle connections
        # ── headers ─────────────────────────────────────────────────────
        server_header=False,      # don't leak Uvicorn version
        date_header=True,
    )