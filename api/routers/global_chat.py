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
import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.database.repository import repo_query
from open_notebook.domain.notebook import ChatSession
from open_notebook.exceptions import NotFoundError
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.utils.graph_utils import get_session_message_count

router = APIRouter()

GLOBAL_CHAT_TAG = "global_chat"


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

async def _build_global_context(query: str, k: int = 5) -> Dict[str, Any]:
    """Retrieve the top-``k`` most relevant chunks from OpenSearch (RAG).

    Uses semantic retrieval rather than dumping every indexed document:
      * User-indexed sources → hybrid search (BM25 + k-NN, RRF-merged).
      * Navy corpus → k-NN search on BGE-M3 embeddings, with a BM25
        fallback inside ``vector_search_navy_documents`` if embedding
        generation fails.

    Notes are excluded so they do not influence the generated responses.
    """
    context_data: Dict[str, Any] = {"sources": [], "navy_corpus": []}
    total_content = ""

    # 1. Search user-indexed sources via OpenSearch hybrid (semantic) search
    try:
        from open_notebook.search import is_opensearch_enabled

        if is_opensearch_enabled():
            from open_notebook.utils.embedding import generate_embedding

            try:
                embedding = await generate_embedding(query)
            except Exception as e:
                logger.warning(
                    f"Global chat: failed to embed query, falling back to BM25: {e}"
                )
                embedding = None

            if embedding:
                from open_notebook.search.query import opensearch_hybrid_search

                results = await opensearch_hybrid_search(
                    query, embedding, results=k, source=True, note=False
                )
            else:
                from open_notebook.search.query import opensearch_text_search

                results = await opensearch_text_search(
                    query, k, source=True, note=False
                )

            logger.info(
                f"Global chat context: OpenSearch returned {len(results) if results else 0} source chunks for query='{query[:80]}'"
            )
            if results:
                for r in results:
                    content = r.get("content", "")
                    if not content and r.get("matches"):
                        content = r["matches"][0] if r["matches"] else ""
                    item = {
                        "id": r.get("id", ""),
                        "parent_id": r.get("parent_id", ""),
                        "title": r.get("title", ""),
                        "content": content,
                    }
                    context_data["sources"].append(item)
                    total_content += content
                # Log unique document IDs
                unique_ids = set(str(r.get("id", "")) for r in results)
                logger.info(
                    f"Global chat context: {len(results)} chunks from {len(unique_ids)} unique source IDs: {unique_ids}"
                )
    except Exception as e:
        logger.warning(f"Global chat: OpenSearch user search failed: {e}")

    # 2. Search navy corpus with semantic kNN (BM25 fallback inside the helper)
    try:
        from open_notebook.search.navy_docs import vector_search_navy_documents

        navy_results = await vector_search_navy_documents(
            query=query, doc_ids=None, k=k
        )
        logger.info(
            f"Global chat context: navy corpus returned {len(navy_results)} chunks for query='{query[:80]}'"
        )
        for r in navy_results:
            label = r.get("doc_id", "")
            section = r.get("section_title", "")
            if section:
                label = f"{label} — {section}"
            page = r.get("page_start")
            if page is not None:
                label += f" (p.{page})"
            item = {
                "id": f"navy:{r.get('doc_id', '')}:p{page or 0}",
                "doc_id": r.get("doc_id", ""),
                "source": r.get("source", ""),
                "title": label,
                "content": r.get("content", ""),
                "page_start": r.get("page_start"),
                "page_end": r.get("page_end"),
            }
            context_data["navy_corpus"].append(item)
            total_content += r.get("content", "")
    except Exception as e:
        logger.warning(f"Global chat: navy corpus search failed: {e}")

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


async def _get_global_sessions() -> List[ChatSession]:
    """Return all chat sessions tagged as global (no notebook relationship)."""
    rows = await repo_query(
        "SELECT * FROM chat_session WHERE owner = $tag ORDER BY updated DESC",
        {"tag": GLOBAL_CHAT_TAG},
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
async def list_global_sessions():
    """List all global chat sessions."""
    try:
        sessions = await _get_global_sessions()
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
async def create_global_session(request: CreateGlobalSessionRequest):
    """Create a new global chat session."""
    try:
        session = ChatSession(
            title=request.title or f"Chat {asyncio.get_event_loop().time():.0f}",
            model_override=request.model_override,
            owner=GLOBAL_CHAT_TAG,
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
async def get_global_session(session_id: str):
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
async def update_global_session(session_id: str, request: UpdateGlobalSessionRequest):
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


@router.delete(
    "/global-chat/sessions/{session_id}",
    response_model=SuccessResponse,
)
async def delete_global_session(session_id: str):
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
async def execute_global_chat(request: ExecuteGlobalChatRequest):
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

        # Build context from all indexed docs
        context = await _build_global_context(request.message)

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
        state_values["context"] = context
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
