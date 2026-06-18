"""
Chat history compression via LLM summarisation.

When a conversation grows beyond MAX_CHAT_CONTEXT_TOKENS the oldest messages
are summarised into a compact SystemMessage and the most-recent turns are kept
verbatim.  This keeps the model within its context budget while preserving the
key facts and decisions from earlier in the conversation.

Two modes:
  - compress_chat_history: in-memory only, used to trim the payload sent to the
    LLM without touching the checkpoint.
  - compress_checkpoint_if_needed: durable, uses RemoveMessage to rewrite the
    checkpoint itself so the summarised history persists across sessions.
"""

import asyncio
import os
from typing import Any, List, Optional

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import RemoveMessage
from loguru import logger

from open_notebook.utils import clean_thinking_content
from open_notebook.utils.text_utils import extract_text_content
from open_notebook.utils.token_utils import token_count

MAX_CHAT_CONTEXT_TOKENS = int(os.getenv("MAX_CHAT_CONTEXT_TOKENS", "80000"))
CHAT_KEEP_RECENT = int(os.getenv("CHAT_KEEP_RECENT_MESSAGES", "10"))


def _messages_token_count(messages: List[BaseMessage]) -> int:
    combined = " ".join(
        m.content if isinstance(m.content, str) else str(m.content)
        for m in messages
    )
    return token_count(combined)


def _build_transcript(messages: List[BaseMessage]) -> str:
    lines: list[str] = []
    for m in messages:
        role = "User" if getattr(m, "type", "") == "human" else "Assistant"
        content = m.content if isinstance(m.content, str) else str(m.content)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def _summarize_messages(
    messages: List[BaseMessage],
    model_id: Optional[str] = None,
) -> Optional[str]:
    """Summarise *messages* using the LLM. Returns None on failure."""
    from open_notebook.ai.provision import provision_langchain_model

    transcript = _build_transcript(messages)
    prompt = (
        "Summarize the following conversation concisely. "
        "Preserve all key facts, decisions, names, references, and conclusions. "
        "Respond in the same language as the conversation. "
        "Do not add information not present in the original.\n\n"
        f"{transcript}"
    )
    try:
        model = await provision_langchain_model(prompt, model_id, "chat", max_tokens=2048)
        result = await model.ainvoke(prompt)
        return clean_thinking_content(extract_text_content(result.content)).strip()
    except Exception as exc:
        logger.warning(f"Chat history summarisation failed: {exc}")
        return None


async def compress_chat_history(
    messages: List[BaseMessage],
    model_id: Optional[str] = None,
    max_tokens: int = MAX_CHAT_CONTEXT_TOKENS,
    keep_recent: int = CHAT_KEEP_RECENT,
) -> List[BaseMessage]:
    """Return a compressed version of *messages* if they exceed *max_tokens*.

    In-memory only — does not write to the checkpoint. Use
    ``compress_checkpoint_if_needed`` for durable compression.
    """
    if not messages:
        return messages

    total = _messages_token_count(messages)
    if total <= max_tokens:
        return messages

    if len(messages) <= keep_recent:
        logger.warning(
            f"Chat history ({total} tokens) exceeds budget ({max_tokens}) but "
            "there are too few messages to compress. Consider raising "
            "MAX_CHAT_CONTEXT_TOKENS or reducing CHAT_KEEP_RECENT_MESSAGES."
        )
        return messages

    old = messages[:-keep_recent]
    recent = messages[-keep_recent:]

    summary = await _summarize_messages(old, model_id=model_id)
    if summary is None:
        logger.warning(
            f"Compression failed; keeping last {keep_recent} messages without summary."
        )
        return list(recent)

    logger.info(
        f"Compressed {len(old)} messages ({total} tokens) into a summary; "
        f"keeping {keep_recent} recent messages verbatim."
    )
    summary_msg = SystemMessage(content=f"[Earlier conversation summary]\n{summary}")
    return [summary_msg] + list(recent)


async def compress_checkpoint_if_needed(
    graph: Any,
    config: RunnableConfig,
    model_id: Optional[str] = None,
    max_tokens: int = MAX_CHAT_CONTEXT_TOKENS,
    keep_recent: int = CHAT_KEEP_RECENT,
) -> None:
    """Durably compress the LangGraph checkpoint when it exceeds the token budget.

    Uses ``RemoveMessage`` to delete old messages from the checkpoint and
    replaces them with an LLM-generated summary ``SystemMessage``.  The
    compressed history is persisted to the SQLite checkpoint so future turns
    start from the summarised state.
    """
    current = await asyncio.to_thread(graph.get_state, config=config)
    if not current or not current.values:
        return

    all_msgs: List[BaseMessage] = current.values.get("messages", [])
    total = _messages_token_count(all_msgs)
    if total <= max_tokens or len(all_msgs) <= keep_recent:
        return

    old = all_msgs[:-keep_recent]

    summary = await _summarize_messages(old, model_id=model_id)
    if summary is None:
        logger.warning("Checkpoint compression skipped: summarisation failed.")
        return

    summary_msg = SystemMessage(
        content=f"[Earlier conversation summary]\n{summary}",
        id="chat_summary",
    )
    remove_ops = [RemoveMessage(id=m.id) for m in old if getattr(m, "id", None)]

    await asyncio.to_thread(
        graph.update_state,
        config,
        {"messages": remove_ops + [summary_msg]},
    )

    logger.info(
        f"Checkpoint compressed: removed {len(old)} messages ({total} tokens), "
        f"kept {keep_recent} recent + summary."
    )
