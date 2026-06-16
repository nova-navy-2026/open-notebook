"""
Global Chat API — chat against all documents indexed in OpenSearch.

Unlike notebook chat, global chat sessions are not scoped to a notebook.
Context is built by performing BM25 search over all indexed documents
(sources, notes, and navy corpus) for the user's query.

Endpoints:
  GET    /global-chat/sessions              — list all global chat sessions
  POST   /global-chat/sessions              — create a new session
  GET    /global-chat/sessions/{session_id}  — get session with messages
  PUT    /global-chat/sessions/{session_id}  — update title / model override
  DELETE /global-chat/sessions/{session_id}  — delete session
  POST   /global-chat/execute               — send a message
"""

import asyncio
import json
import re
import traceback
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import BaseModel, Field

from api.auth import get_current_user_id, get_navy_acl_user_id
from open_notebook.database.repository import repo_query
from open_notebook.domain.notebook import ChatSession
from open_notebook.exceptions import NotFoundError
from open_notebook.graphs.chat import astream_chat_response
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.utils.graph_utils import get_session_message_count

router = APIRouter()

GLOBAL_CHAT_TAG = "global_chat"


def _owner_tag(user_id: str) -> str:
    """Build the per-user owner tag stored on global chat sessions."""
    return f"{GLOBAL_CHAT_TAG}:{user_id or 'anonymous'}"


def _session_belongs_to_user(session: "ChatSession", user_id: str) -> bool:
    """Return True if the session is owned by ``user_id``.

    Sessions created before per-user isolation (owner=None or
    owner=GLOBAL_CHAT_TAG) are treated as legacy and accessible by any
    authenticated user, the same way notebooks without an owner are handled.
    """
    owner = getattr(session, "owner", None)
    # Legacy: no owner set, or the old hardcoded tag — accessible to all.
    if not owner or owner == GLOBAL_CHAT_TAG:
        return True
    return owner == _owner_tag(user_id)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateGlobalSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="Optional session title")
    model_override: Optional[str] = Field(
        None, description="Optional model override for this session"
    )


class UpdateGlobalSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="New session title")
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )


class ChatMessage(BaseModel):
    id: str
    type: str
    content: str
    timestamp: Optional[str] = None


class GlobalChatSessionResponse(BaseModel):
    id: str
    title: str
    created: str
    updated: str
    message_count: Optional[int] = None
    model_override: Optional[str] = None


class GlobalChatSessionWithMessagesResponse(GlobalChatSessionResponse):
    messages: List[ChatMessage] = Field(default_factory=list)


class ExecuteGlobalChatRequest(BaseModel):
    session_id: str = Field(..., description="Chat session ID")
    message: str = Field(..., description="User message content")
    model_override: Optional[str] = Field(
        None, description="Optional model override for this message"
    )
    agent_instruction: Optional[str] = Field(
        None,
        description="Optional internal instruction for a chat agent mode",
    )


class PersistGlobalChatExchangeRequest(BaseModel):
    user_message: str = Field(..., description="User message to persist")
    assistant_message: str = Field(..., description="Assistant message to persist")
    user_message_id: Optional[str] = Field(
        None, description="Stable user message id for updates/replacements"
    )
    assistant_message_id: Optional[str] = Field(
        None, description="Stable assistant message id for updates/replacements"
    )


class ExecuteGlobalChatResponse(BaseModel):
    session_id: str
    messages: List[ChatMessage]
    context_stats: Optional[Dict[str, Any]] = None


class SuccessResponse(BaseModel):
    success: bool = True
    message: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _search_terms(query: str) -> List[str]:
    words = re.findall(r"[\wÀ-ÿ]{3,}", (query or "").lower())
    stop = {
        "com", "das", "dos", "para", "por", "que", "uma", "este", "esta",
        "isto", "sobre", "the", "and", "for", "with", "what", "from",
    }
    return [word for word in words if word not in stop]


async def _search_surreal_sources(
    query: str,
    k: int,
    auth_user_id: str,
) -> List[Dict[str, Any]]:
    """Search app-uploaded SurrealDB sources for the authenticated app user."""
    terms = _search_terms(query)
    if not terms:
        return []

    try:
        rows = await repo_query(
            """
            SELECT id, title, full_text, caption, file_mime, owner, updated
            FROM source
            WHERE (
                owner = $owner OR owner IS NULL OR owner = NONE
            )
            AND (
                full_text != NONE OR caption != NONE
            )
            ORDER BY updated DESC
            LIMIT 250
            """,
            {"owner": auth_user_id},
        )
    except Exception as e:
        logger.warning(f"Global chat: SurrealDB source search failed: {e}")
        return []

    scored: List[tuple[int, Dict[str, Any]]] = []
    for row in rows or []:
        source_id = str(row.get("id") or "")
        title = str(row.get("title") or source_id or "Source")
        caption = str(row.get("caption") or "")
        full_text = str(row.get("full_text") or "")
        content = "\n\n".join(part for part in [caption, full_text] if part.strip())
        haystack = f"{title}\n{content}".lower()
        score = sum(haystack.count(term) for term in terms)
        if score <= 0:
            continue
        if len(content) > 5000:
            content = content[:5000].rstrip() + "\n\n[excerto truncado]"
        scored.append(
            (
                score,
                {
                    "id": source_id,
                    "parent_id": source_id,
                    "title": title,
                    "content": content,
                    "file_mime": row.get("file_mime"),
                    "storage": "surrealdb",
                },
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:k]]


async def _search_navy_corpus(
    query: str, k: int, user_id: Optional[str]
) -> List[Dict[str, Any]]:
    """Semantic k-NN search over the navy corpus for one query. Never raises."""
    out: List[Dict[str, Any]] = []
    try:
        from open_notebook.search.navy_docs import vector_search_navy_documents

        navy_results = await vector_search_navy_documents(
            query=query, doc_ids=None, k=k, user_id=user_id
        )
        for r in navy_results:
            label = r.get("doc_id", "")
            section = r.get("section_title", "")
            if section:
                label = f"{label} — {section}"
            page = r.get("page_start")
            if page is not None:
                label += f" (p.{page})"
            out.append(
                {
                    "id": f"navy:{r.get('doc_id', '')}:p{page or 0}",
                    "doc_id": r.get("doc_id", ""),
                    "source": r.get("source", ""),
                    "title": label,
                    "content": r.get("content", ""),
                    "page_start": r.get("page_start"),
                    "page_end": r.get("page_end"),
                }
            )
    except Exception as e:
        logger.warning(f"Global chat: navy corpus search failed: {e}")
    return out


async def _build_global_context(
    query: str,
    k: int = 5,
    user_id: Optional[str] = None,
    auth_user_id: str = "anonymous",
) -> Dict[str, Any]:
    """Retrieve relevant app uploads and ACL-filtered Navy corpus chunks.

    Uses retrieval rather than dumping every indexed document:
      * App uploads → SurrealDB source text/captions owned by the app user.
      * Navy corpus → OpenSearch k-NN on BGE-M3 embeddings, filtered by the
        user's department/clearance ACL, with a BM25
        fallback inside ``vector_search_navy_documents`` if embedding
        generation fails.

    Metaprompting: the user's message is first expanded into a few pt-PT / EN
    query variants (``rewrite_search_query``); every variant is searched in
    parallel and the chunks are merged (deduped by id) so recall on the
    multilingual navy corpus improves. Falls back to the single original
    query when rewriting is disabled or fails.

    Notes are excluded so they do not influence the generated responses.
    """
    context_data: Dict[str, Any] = {"sources": [], "navy_corpus": []}
    total_content = ""

    # 0. Metaprompting — expand the query into retrieval-friendly variants.
    from open_notebook.search.query_rewrite import rewrite_search_query

    variants = await rewrite_search_query(query, max_variants=2)
    if len(variants) > 1:
        logger.info(
            f"Global chat: query expanded into {len(variants)} variants: {variants}"
        )
    # Spread the budget across variants so the merged set stays around ``k``.
    per_query = max(2, k // max(1, len(variants) - 1)) if len(variants) > 1 else k

    # 1+2. Search app uploads and the ACL-filtered navy corpus for every variant.
    search_tasks = []
    for v in variants:
        search_tasks.append(_search_surreal_sources(v, per_query, auth_user_id))
        search_tasks.append(_search_navy_corpus(v, per_query, user_id))
    results_per_task = await asyncio.gather(*search_tasks, return_exceptions=True)

    seen_source_ids: set = set()
    seen_navy_ids: set = set()
    for idx, task_result in enumerate(results_per_task):
        if isinstance(task_result, Exception):
            logger.warning(f"Global chat: variant search task failed: {task_result}")
            continue
        task_kind = idx % 2
        is_navy = task_kind == 1
        for item in task_result:
            item_id = item.get("id", "")
            if is_navy:
                if item_id and item_id in seen_navy_ids:
                    continue
                if item_id:
                    seen_navy_ids.add(item_id)
                context_data["navy_corpus"].append(item)
            else:
                if item_id and item_id in seen_source_ids:
                    continue
                if item_id:
                    seen_source_ids.add(item_id)
                context_data["sources"].append(item)
            total_content += item.get("content", "")

    # ------------------------------------------------------------------
    # Aggregate chunks into document-level summaries
    # ------------------------------------------------------------------
    documents: List[Dict[str, Any]] = []

    # Sources: group by parent_id
    source_docs: Dict[str, Dict[str, Any]] = {}
    for r in context_data["sources"]:
        pid = r.get("parent_id") or r.get("id", "")
        if pid not in source_docs:
            source_docs[pid] = {
                "name": r.get("title", pid),
                "type": "source",
                "pages": [],
                "chunks": 0,
            }
        source_docs[pid]["chunks"] += 1
    for doc in source_docs.values():
        documents.append(doc)

    # Navy: group by doc_id, collect page numbers
    navy_docs: Dict[str, Dict[str, Any]] = {}
    for r in context_data["navy_corpus"]:
        did = r.get("doc_id") or r.get("id", "")
        if did not in navy_docs:
            navy_docs[did] = {
                "name": did,
                "type": "navy",
                "pages": [],
                "chunks": 0,
            }
        navy_docs[did]["chunks"] += 1
        ps = r.get("page_start")
        pe = r.get("page_end")
        if ps is not None:
            navy_docs[did]["pages"].append(ps)
        if pe is not None and pe != ps:
            navy_docs[did]["pages"].append(pe)
    for doc in navy_docs.values():
        doc["pages"] = sorted(set(doc["pages"]))
        documents.append(doc)

    context_data["documents"] = documents

    logger.info(
        f"Global chat context total: {len(context_data['sources'])} source chunks from "
        f"{len(source_docs)} docs, {len(context_data['navy_corpus'])} navy chunks from "
        f"{len(navy_docs)} docs, {len(total_content)} chars"
    )
    return context_data


def _context_with_agent_instruction(
    context: Dict[str, Any],
    agent_instruction: Optional[str],
) -> Dict[str, Any]:
    return {
        "agent_instruction": agent_instruction,
        "retrieved_context": _format_global_context_for_prompt(context),
    }


def _format_global_context_for_prompt(context: Dict[str, Any]) -> str:
    """Render retrieved global-chat context without internal control fields."""
    parts: List[str] = []

    if context.get("sources"):
        parts.append("## Indexed sources")
        for item in context["sources"]:
            title = item.get("title") or item.get("id") or "Source"
            content = item.get("content") or ""
            if content.strip():
                parts.append(f"### {title}\n{content}")

    if context.get("navy_corpus"):
        parts.append("## Navy corpus")
        for item in context["navy_corpus"]:
            title = item.get("title") or item.get("doc_id") or "Document"
            content = item.get("content") or ""
            if content.strip():
                parts.append(f"### {title}\n{content}")

    if not parts:
        return "No relevant excerpts were retrieved."

    return "\n\n".join(parts)


async def _get_global_sessions(user_id: str) -> List[ChatSession]:
    """Return all chat sessions tagged as global for the given user.

    Includes legacy sessions (owner IS NULL or owner = 'global_chat') so
    that pre-existing sessions remain visible and deletable by the current
    user.
    """
    rows = await repo_query(
        "SELECT * FROM chat_session WHERE owner = $tag "
        "OR owner IS NULL "
        "OR owner = $legacy_tag "
        "ORDER BY updated DESC",
        {"tag": _owner_tag(user_id), "legacy_tag": GLOBAL_CHAT_TAG},
    )
    sessions: List[ChatSession] = []
    for row in rows:
        try:
            sessions.append(ChatSession(**row))
        except Exception as e:
            logger.warning(f"Skipping malformed global session: {e}")
    return sessions


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/global-chat/sessions", response_model=List[GlobalChatSessionResponse])
async def list_global_sessions(user_id: str = Depends(get_current_user_id)):
    """List all global chat sessions for the authenticated user."""
    try:
        sessions = await _get_global_sessions(user_id)
        results = []
        for session in sessions:
            session_id = str(session.id)
            msg_count = await get_session_message_count(chat_graph, session_id)
            results.append(
                GlobalChatSessionResponse(
                    id=session.id or "",
                    title=session.title or "Untitled Session",
                    created=str(session.created),
                    updated=str(session.updated),
                    message_count=msg_count,
                    model_override=getattr(session, "model_override", None),
                )
            )
        return results
    except Exception as e:
        logger.error(f"Error listing global chat sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/global-chat/sessions", response_model=GlobalChatSessionResponse)
async def create_global_session(
    request: CreateGlobalSessionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Create a new global chat session, scoped to the authenticated user."""
    try:
        session = ChatSession(
            title=request.title or f"Chat {asyncio.get_event_loop().time():.0f}",
            model_override=request.model_override,
            owner=_owner_tag(user_id),
        )
        await session.save()

        return GlobalChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            created=str(session.created),
            updated=str(session.updated),
            message_count=0,
            model_override=session.model_override,
        )
    except Exception as e:
        logger.error(f"Error creating global chat session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/global-chat/sessions/{session_id}",
    response_model=GlobalChatSessionWithMessagesResponse,
)
async def get_global_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get a global chat session with its messages."""
    try:
        full_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not _session_belongs_to_user(session, user_id):
            raise HTTPException(status_code=404, detail="Session not found")

        thread_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_id}),
        )

        messages: List[ChatMessage] = []
        if thread_state and thread_state.values and "messages" in thread_state.values:
            for msg in thread_state.values["messages"]:
                messages.append(
                    ChatMessage(
                        id=getattr(msg, "id", f"msg_{len(messages)}"),
                        type=msg.type if hasattr(msg, "type") else "unknown",
                        content=msg.content if hasattr(msg, "content") else str(msg),
                    )
                )

        return GlobalChatSessionWithMessagesResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            created=str(session.created),
            updated=str(session.updated),
            message_count=len(messages),
            messages=messages,
            model_override=getattr(session, "model_override", None),
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching global session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/global-chat/sessions/{session_id}",
    response_model=GlobalChatSessionResponse,
)
async def update_global_session(
    session_id: str,
    request: UpdateGlobalSessionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Update a global chat session."""
    try:
        full_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not _session_belongs_to_user(session, user_id):
            raise HTTPException(status_code=404, detail="Session not found")

        data = request.model_dump(exclude_unset=True)
        if "title" in data:
            session.title = data["title"]
        if "model_override" in data:
            session.model_override = data["model_override"]
        await session.save()

        msg_count = await get_session_message_count(chat_graph, full_id)

        return GlobalChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            created=str(session.created),
            updated=str(session.updated),
            message_count=msg_count,
            model_override=session.model_override,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating global session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/global-chat/sessions/{session_id}/messages",
    response_model=GlobalChatSessionWithMessagesResponse,
)
async def persist_global_chat_exchange(
    session_id: str,
    request: PersistGlobalChatExchangeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Persist a user/assistant exchange produced outside the normal chat graph."""
    try:
        full_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not _session_belongs_to_user(session, user_id):
            raise HTTPException(status_code=404, detail="Session not found")

        from langchain_core.messages import AIMessage, HumanMessage

        await asyncio.to_thread(
            chat_graph.update_state,
            RunnableConfig(configurable={"thread_id": full_id}),
            {
                "messages": [
                    HumanMessage(
                        content=request.user_message,
                        id=request.user_message_id,
                    ),
                    AIMessage(
                        content=request.assistant_message,
                        id=request.assistant_message_id,
                    ),
                ]
            },
        )
        await session.save()

        thread_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_id}),
        )

        messages: List[ChatMessage] = []
        if thread_state and thread_state.values and "messages" in thread_state.values:
            for msg in thread_state.values["messages"]:
                messages.append(
                    ChatMessage(
                        id=getattr(msg, "id", f"msg_{len(messages)}"),
                        type=msg.type if hasattr(msg, "type") else "unknown",
                        content=msg.content if hasattr(msg, "content") else str(msg),
                    )
                )

        return GlobalChatSessionWithMessagesResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            created=str(session.created),
            updated=str(session.updated),
            message_count=len(messages),
            messages=messages,
            model_override=getattr(session, "model_override", None),
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error persisting global chat exchange: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/global-chat/sessions/{session_id}",
    response_model=SuccessResponse,
)
async def delete_global_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Delete a global chat session."""
    try:
        full_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not _session_belongs_to_user(session, user_id):
            raise HTTPException(status_code=404, detail="Session not found")

        await session.delete()
        return SuccessResponse(success=True, message="Session deleted successfully")
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting global session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/global-chat/execute", response_model=ExecuteGlobalChatResponse)
async def execute_global_chat(
    request: ExecuteGlobalChatRequest,
    user_id: Optional[str] = Depends(get_navy_acl_user_id),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Send a message in a global chat session.

    Context is automatically built by searching all indexed documents
    for the user's message.
    """
    try:
        full_id = (
            request.session_id
            if request.session_id.startswith("chat_session:")
            else f"chat_session:{request.session_id}"
        )
        session = await ChatSession.get(full_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not _session_belongs_to_user(session, auth_user_id):
            raise HTTPException(status_code=404, detail="Session not found")

        # Build context from app uploads plus ACL-filtered Navy corpus.
        context = await _build_global_context(
            request.message,
            user_id=user_id,
            auth_user_id=auth_user_id,
        )
        context_for_prompt = _context_with_agent_instruction(
            context,
            request.agent_instruction,
        )
        if request.agent_instruction:
            logger.info(
                "ChatAgent text instruction | surface=global_chat session={} "
                "instruction={!r} message_preview={!r}",
                full_id,
                request.agent_instruction.splitlines()[0],
                request.message[:180],
            )

        model_override = (
            request.model_override
            if request.model_override is not None
            else getattr(session, "model_override", None)
        )

        current_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_id}),
        )

        state_values = current_state.values if current_state else {}
        state_values["messages"] = state_values.get("messages", [])
        state_values["context"] = context_for_prompt
        state_values["model_override"] = model_override
        state_values["prompt_template"] = "global_chat/system"

        from langchain_core.messages import HumanMessage

        state_values["messages"].append(HumanMessage(content=request.message))

        result = chat_graph.invoke(
            input=state_values,
            config=RunnableConfig(
                configurable={
                    "thread_id": full_id,
                    "model_id": model_override,
                }
            ),
        )

        await session.save()

        messages: List[ChatMessage] = []
        for msg in result.get("messages", []):
            messages.append(
                ChatMessage(
                    id=getattr(msg, "id", f"msg_{len(messages)}"),
                    type=msg.type if hasattr(msg, "type") else "unknown",
                    content=msg.content if hasattr(msg, "content") else str(msg),
                )
            )

        context_stats = {
            "sources_count": len(context.get("sources", [])),
            "notes_count": 0,
            "navy_corpus_count": len(context.get("navy_corpus", [])),
            "documents": context.get("documents", []),
        }

        return ExecuteGlobalChatResponse(
            session_id=request.session_id,
            messages=messages,
            context_stats=context_stats,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error executing global chat: {e}\n"
            f"  Session: {request.session_id}\n"
            f"  Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"Error executing global chat: {e}")


async def _stream_global_chat_sse(
    session_id: str,
    user_message: str,
    context: Dict[str, Any],
    context_stats: Dict[str, Any],
    model_override: Optional[str],
    agent_instruction: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Wrap ``astream_chat_response`` as Server-Sent Events for global chat."""
    yield f"data: {json.dumps({'type': 'user_message', 'content': user_message})}\n\n"
    yield f"data: {json.dumps({'type': 'context_stats', 'data': context_stats})}\n\n"
    try:
        async for event in astream_chat_response(
            session_id=session_id,
            user_message=user_message,
            context=_context_with_agent_instruction(context, agent_instruction),
            model_override=model_override,
            prompt_template="global_chat/system",
        ):
            yield f"data: {json.dumps(event)}\n\n"
    except Exception as e:
        logger.error(f"Error in global chat stream: {e}\n{traceback.format_exc()}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.post("/global-chat/execute/stream")
async def execute_global_chat_stream(
    request: ExecuteGlobalChatRequest,
    user_id: Optional[str] = Depends(get_navy_acl_user_id),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Send a message in a global chat session with SSE token streaming."""
    full_id = (
        request.session_id
        if request.session_id.startswith("chat_session:")
        else f"chat_session:{request.session_id}"
    )
    session = await ChatSession.get(full_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _session_belongs_to_user(session, auth_user_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Build context from app uploads plus ACL-filtered Navy corpus.
    context = await _build_global_context(
        request.message,
        user_id=user_id,
        auth_user_id=auth_user_id,
    )
    if request.agent_instruction:
        logger.info(
            "ChatAgent text instruction | surface=global_chat session={} "
            "instruction={!r} message_preview={!r}",
            full_id,
            request.agent_instruction.splitlines()[0],
            request.message[:180],
        )

    model_override = (
        request.model_override
        if request.model_override is not None
        else getattr(session, "model_override", None)
    )

    context_stats = {
        "sources_count": len(context.get("sources", [])),
        "notes_count": 0,
        "navy_corpus_count": len(context.get("navy_corpus", [])),
        "documents": context.get("documents", []),
    }

    await session.save()

    return StreamingResponse(
        _stream_global_chat_sse(
            session_id=full_id,
            user_message=request.message,
            context=context,
            context_stats=context_stats,
            model_override=model_override,
            agent_instruction=request.agent_instruction,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
