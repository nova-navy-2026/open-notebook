#!/usr/bin/env python3
"""
Startup script for Open Notebook API server.
"""

import atexit
import os
import shutil
import signal
import subprocess
import sys
import multiprocessing
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# Add the current directory to Python path so imports work
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# Load .env early so both the API and the background worker subprocess we
# spawn below inherit the SurrealDB credentials and other configuration.
load_dotenv(current_dir / ".env")


def start_background_worker() -> "subprocess.Popen | None":
    """
    Start the surreal-commands worker that processes queued jobs
    (source ingestion, embeddings, podcasts, ...).

    The Sources tab submits work asynchronously, so without this worker
    uploads stay stuck on "Processing..." forever. Running it here means a
    single `python run_api.py` brings up both the API and the worker.

    Disable by setting START_WORKER=false (e.g. when running the worker as a
    separate service via supervisord/Docker).
    """
    if os.getenv("START_WORKER", "true").lower() != "true":
        print("START_WORKER=false -> skipping background worker startup")
        return None

    worker_bin = shutil.which("surreal-commands-worker")
    if not worker_bin:
        print(
            "WARNING: 'surreal-commands-worker' not found on PATH; "
            "background jobs (source processing, embeddings) will NOT run. "
            "Install it or set START_WORKER=false to silence this warning."
        )
        return None

    # The worker reads SurrealDB creds from the environment. repository.py
    # accepts SURREAL_PASS or SURREAL_PASSWORD, but the ensure-command-table
    # helper only reads SURREAL_PASSWORD, so mirror it for consistency.
    worker_env = os.environ.copy()
    if "SURREAL_PASSWORD" not in worker_env and worker_env.get("SURREAL_PASS"):
        worker_env["SURREAL_PASSWORD"] = worker_env["SURREAL_PASS"]

    # Make sure the `command` table exists before the worker opens its LIVE
    # query on it (otherwise the worker can crash on first start).
    ensure_script = current_dir / "scripts" / "ensure-command-table.py"
    if ensure_script.is_file():
        try:
            subprocess.run(
                [sys.executable, str(ensure_script)],
                cwd=str(current_dir),
                env=worker_env,
                check=False,
                timeout=90,
            )
        except Exception as exc:  # best-effort; table usually already exists
            print(f"WARNING: ensure-command-table step failed: {exc}")

    max_tasks = os.getenv("WORKER_MAX_TASKS", "5")
    cmd = [
        worker_bin,
        "--import-modules",
        "commands",
        "--max-tasks",
        str(max_tasks),
    ]
    print(f"Starting background worker: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=str(current_dir), env=worker_env)

    def _stop_worker(*_args) -> None:
        if proc.poll() is None:
            print("Stopping background worker...")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    atexit.register(_stop_worker)
    # Ensure the worker is torn down if the API receives a termination signal.
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            prev_handler = signal.getsignal(sig)

            def _handler(signum, frame, _prev=prev_handler):
                _stop_worker()
                if callable(_prev):
                    _prev(signum, frame)
                else:
                    raise SystemExit(0)

            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Signals can only be set in the main thread; ignore otherwise.
            pass

    return proc

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

    # Start the background job worker alongside the API so a single command
    # boots the whole stack. Controlled via START_WORKER (default: true).
    start_background_worker()

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