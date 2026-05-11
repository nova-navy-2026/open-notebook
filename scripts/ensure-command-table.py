"""
Ensure the `command` table exists in SurrealDB before the surreal-commands
worker starts. The worker opens a LIVE query on this table during startup; if
the table does not yet exist, the LIVE subscription raises NotFound and the
worker crashes. This script is idempotent: DEFINE TABLE IF NOT EXISTS.
"""

from __future__ import annotations

import asyncio
import os
import sys

from surrealdb import AsyncSurreal


SURREAL_URL = os.environ.get("SURREAL_URL", "ws://localhost:8000/rpc")
SURREAL_USER = os.environ.get("SURREAL_USER", "root")
SURREAL_PASSWORD = os.environ.get("SURREAL_PASSWORD", "root")
SURREAL_NAMESPACE = os.environ.get("SURREAL_NAMESPACE", "open_notebook")
SURREAL_DATABASE = os.environ.get("SURREAL_DATABASE", "open_notebook")

DDL = "DEFINE TABLE IF NOT EXISTS command SCHEMALESS;"


async def main() -> int:
    last_err: Exception | None = None
    for attempt in range(1, 31):  # up to ~60s
        try:
            db = AsyncSurreal(SURREAL_URL)
            await db.signin({"username": SURREAL_USER, "password": SURREAL_PASSWORD})
            await db.use(SURREAL_NAMESPACE, SURREAL_DATABASE)
            await db.query(DDL)
            await db.close()
            print(f"[ensure-command-table] OK (attempt {attempt})")
            return 0
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[ensure-command-table] attempt {attempt} failed: {exc}", file=sys.stderr)
            await asyncio.sleep(2)
    print(f"[ensure-command-table] giving up: {last_err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
