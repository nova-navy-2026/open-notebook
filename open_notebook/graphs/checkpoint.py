"""Shared SQLite checkpointer for all LangGraph graphs.

Opening one connection per graph module leads to two writers on the same
SQLite file. WAL mode serialises concurrent writes, but a single shared
connection is simpler and removes any risk of readers seeing inconsistent
checkpoint state between graph modules.
"""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from open_notebook.config import LANGGRAPH_CHECKPOINT_FILE

_conn = sqlite3.connect(
    LANGGRAPH_CHECKPOINT_FILE,
    check_same_thread=False,
)
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("PRAGMA busy_timeout=5000")

checkpointer = SqliteSaver(_conn)
