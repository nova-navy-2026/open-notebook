import asyncio
import json
import traceback
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import BaseModel, Field

from api.auth import get_current_user_id, get_navy_acl_user_id
from open_notebook.ai.vision import is_visual_mime
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import ChatSession, Note, Notebook, Source
from open_notebook.exceptions import (
    NotFoundError,
)
from open_notebook.graphs.chat import astream_chat_response
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.utils.graph_utils import get_session_message_count

router = APIRouter()


# Request/Response models
class CreateSessionRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID to create session for")
    title: Optional[str] = Field(None, description="Optional session title")
    model_override: Optional[str] = Field(
        None, description="Optional model override for this session"
    )


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="New session title")
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )


class ChatMessage(BaseModel):
    id: str = Field(..., description="Message ID")
    type: str = Field(..., description="Message type (human|ai)")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="Message timestamp")


class ChatSessionResponse(BaseModel):
    id: str = Field(..., description="Session ID")
    title: str = Field(..., description="Session title")
    notebook_id: Optional[str] = Field(None, description="Notebook ID")
    created: str = Field(..., description="Creation timestamp")
    updated: str = Field(..., description="Last update timestamp")
    message_count: Optional[int] = Field(
        None, description="Number of messages in session"
    )
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )


class ChatSessionWithMessagesResponse(ChatSessionResponse):
    messages: List[ChatMessage] = Field(
        default_factory=list, description="Session messages"
    )


class ExecuteChatRequest(BaseModel):
    session_id: str = Field(..., description="Chat session ID")
    message: str = Field(..., description="User message content")
    context: Dict[str, Any] = Field(
        ..., description="Chat context with sources and notes"
    )
    model_override: Optional[str] = Field(
        None, description="Optional model override for this message"
    )
    agent_instruction: Optional[str] = Field(
        None,
        description="Optional internal instruction for a chat agent mode",
    )


class ExecuteChatResponse(BaseModel):
    session_id: str = Field(..., description="Session ID")
    messages: List[ChatMessage] = Field(..., description="Updated message list")


class PersistChatExchangeRequest(BaseModel):
    user_message: str = Field(..., description="User message to persist")
    assistant_message: str = Field(..., description="Assistant message to persist")
    user_message_id: Optional[str] = Field(
        None, description="Stable user message id for updates/replacements"
    )
    assistant_message_id: Optional[str] = Field(
        None, description="Stable assistant message id for updates/replacements"
    )


class BuildContextRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID")
    context_config: Dict[str, Any] = Field(..., description="Context configuration")
    query: Optional[str] = Field(None, description="User query for relevance-based corpus search")


class BuildContextResponse(BaseModel):
    context: Dict[str, Any] = Field(..., description="Built context data")
    token_count: int = Field(..., description="Estimated token count")
    char_count: int = Field(..., description="Character count")


class SuccessResponse(BaseModel):
    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Success message")


def _full_session_id(session_id: str) -> str:
    return (
        session_id
        if session_id.startswith("chat_session:")
        else f"chat_session:{session_id}"
    )


async def _ensure_notebook_access(notebook: Notebook, user_id: str) -> None:
    """Allow the owner, a legacy ownerless notebook, or a collaborative member.

    Chat sessions stay per-user, but a member must be able to open chats on a
    shared notebook, so notebook access here is membership-aware.
    """
    owner = getattr(notebook, "owner", None)
    if owner is None or owner == user_id:
        return
    from open_notebook.domain.collaboration import get_member

    if await get_member(str(notebook.id), user_id) is not None:
        return
    raise HTTPException(status_code=404, detail="Notebook not found")


async def _can_use_object(
    obj: Any, user_id: str, member_notebook_ids: List[str], relation: str
) -> bool:
    """True when ``user_id`` may pull ``obj`` (a source/note) into chat context:
    they own it, it is ownerless legacy data, or it is shared into a
    collaborative notebook they belong to. ``relation`` is ``reference`` for
    sources, ``artifact`` for notes."""
    owner = getattr(obj, "owner", None)
    if owner is None or owner == user_id:
        return True
    from api.collaboration_access import _resource_in_member_notebook

    return await _resource_in_member_notebook(
        str(obj.id), relation, member_notebook_ids
    )


def _is_visual_source(source: Source) -> bool:
    return is_visual_mime(getattr(source, "file_mime", None))


async def _build_source_context_for_chat(
    source: Source,
    status: str,
) -> Dict[str, Any]:
    """Build source context with a visual-source fallback for notebook chat."""
    if "full content" in status:
        return await source.get_context(context_size="long")

    source_context = await source.get_context(context_size="short")
    insights = source_context.get("insights") or []

    # For images/videos, the generated caption is the actual searchable
    # representation. Even if insights exist, include the visual description so
    # questions like "summarize this video" use the uploaded source instead of
    # drifting into the conversation history.
    if _is_visual_source(source):
        visual_text = source.caption or source.full_text
        source_context["content_type"] = "video" if str(source.file_mime).startswith("video/") else "image"
        if visual_text:
            source_context["caption"] = visual_text
            source_context["full_text"] = visual_text
            source_context["visual_content"] = visual_text
        else:
            source_context["processing_status"] = (
                "Visual source selected, but caption processing has not completed yet. "
                "The assistant cannot summarize this image/video until processing succeeds."
            )
            source_context["full_text"] = source_context["processing_status"]

    return source_context


async def _get_session_notebook_id(full_session_id: str) -> Optional[str]:
    notebook_query = await repo_query(
        "SELECT out FROM refers_to WHERE in = $session_id",
        {"session_id": ensure_record_id(full_session_id)},
    )
    return notebook_query[0]["out"] if notebook_query else None


async def _ensure_session_access(full_session_id: str, user_id: str) -> Optional[str]:
    notebook_id = await _get_session_notebook_id(full_session_id)
    if not notebook_id:
        raise HTTPException(status_code=404, detail="Session not found")
    notebook = await Notebook.get(str(notebook_id))
    if not notebook:
        raise HTTPException(status_code=404, detail="Session not found")
    await _ensure_notebook_access(notebook, user_id)
    return str(notebook_id)


def _context_with_agent_instruction(
    context: Dict[str, Any],
    agent_instruction: Optional[str],
) -> Dict[str, Any]:
    if not agent_instruction:
        return context
    return {
        "agent_instruction": agent_instruction,
        "selected_context": context,
    }


@router.get("/chat/sessions", response_model=List[ChatSessionResponse])
async def get_sessions(
    notebook_id: str = Query(..., description="Notebook ID"),
    user_id: str = Depends(get_current_user_id),
):
    """Get all chat sessions for a notebook."""
    try:
        # Get notebook to verify it exists
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        await _ensure_notebook_access(notebook, user_id)

        # Get sessions for this notebook
        sessions_list = await notebook.get_chat_sessions()

        results = []
        for session in sessions_list:
            session_id = str(session.id)

            # Get message count from LangGraph state
            msg_count = await get_session_message_count(chat_graph, session_id)

            results.append(
                ChatSessionResponse(
                    id=session.id or "",
                    title=session.title or "Untitled Session",
                    notebook_id=notebook_id,
                    created=str(session.created),
                    updated=str(session.updated),
                    message_count=msg_count,
                    model_override=getattr(session, "model_override", None),
                )
            )

        return results
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error fetching chat sessions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching chat sessions: {str(e)}"
        )


@router.post("/chat/sessions", response_model=ChatSessionResponse)
async def create_session(
    request: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Create a new chat session."""
    try:
        # Verify notebook exists
        notebook = await Notebook.get(request.notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        await _ensure_notebook_access(notebook, user_id)

        # Create new session
        session = ChatSession(
            title=request.title
            or f"Chat Session {asyncio.get_running_loop().time():.0f}",
            model_override=request.model_override,
            owner=user_id,
        )
        await session.save()

        # Relate session to notebook
        await session.relate_to_notebook(request.notebook_id)

        return ChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            notebook_id=request.notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=0,
            model_override=session.model_override,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error creating chat session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating chat session: {str(e)}"
        )


@router.get(
    "/chat/sessions/{session_id}", response_model=ChatSessionWithMessagesResponse
)
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get a specific session with its messages."""
    try:
        # Get session
        # Ensure session_id has proper table prefix
        full_session_id = _full_session_id(session_id)
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        notebook_id = await _ensure_session_access(full_session_id, user_id)

        # Get session state from LangGraph to retrieve messages
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        thread_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Extract messages from state
        messages: list[ChatMessage] = []
        if thread_state and thread_state.values and "messages" in thread_state.values:
            for msg in thread_state.values["messages"]:
                messages.append(
                    ChatMessage(
                        id=getattr(msg, "id", f"msg_{len(messages)}"),
                        type=msg.type if hasattr(msg, "type") else "unknown",
                        content=msg.content if hasattr(msg, "content") else str(msg),
                        timestamp=None,  # LangChain messages don't have timestamps by default
                    )
                )

        return ChatSessionWithMessagesResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            notebook_id=notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=len(messages),
            messages=messages,
            model_override=getattr(session, "model_override", None),
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error fetching session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching session: {str(e)}")


@router.put("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: str,
    request: UpdateSessionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Update session title."""
    try:
        # Ensure session_id has proper table prefix
        full_session_id = _full_session_id(session_id)
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        notebook_id = await _ensure_session_access(full_session_id, user_id)

        update_data = request.model_dump(exclude_unset=True)

        if "title" in update_data:
            session.title = update_data["title"]

        if "model_override" in update_data:
            session.model_override = update_data["model_override"]

        await session.save()

        # Get message count from LangGraph state
        msg_count = await get_session_message_count(chat_graph, full_session_id)

        return ChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            notebook_id=notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=msg_count,
            model_override=session.model_override,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error updating session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating session: {str(e)}")


@router.post(
    "/chat/sessions/{session_id}/messages",
    response_model=ChatSessionWithMessagesResponse,
)
async def persist_chat_exchange(
    session_id: str,
    request: PersistChatExchangeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Persist a user/assistant exchange produced outside the normal chat graph."""
    try:
        full_session_id = _full_session_id(session_id)
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        notebook_id = await _ensure_session_access(full_session_id, user_id)

        from langchain_core.messages import AIMessage, HumanMessage

        await asyncio.to_thread(
            chat_graph.update_state,
            RunnableConfig(configurable={"thread_id": full_session_id}),
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
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        messages: list[ChatMessage] = []
        if thread_state and thread_state.values and "messages" in thread_state.values:
            for msg in thread_state.values["messages"]:
                messages.append(
                    ChatMessage(
                        id=getattr(msg, "id", f"msg_{len(messages)}"),
                        type=msg.type if hasattr(msg, "type") else "unknown",
                        content=msg.content if hasattr(msg, "content") else str(msg),
                        timestamp=None,
                    )
                )

        return ChatSessionWithMessagesResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            notebook_id=notebook_id,
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
        logger.error(f"Error persisting chat exchange: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error persisting chat exchange: {str(e)}")


@router.delete("/chat/sessions/{session_id}", response_model=SuccessResponse)
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Delete a chat session."""
    try:
        # Ensure session_id has proper table prefix
        full_session_id = _full_session_id(session_id)
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        await _ensure_session_access(full_session_id, user_id)

        await session.delete()

        return SuccessResponse(success=True, message="Session deleted successfully")
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")


@router.post("/chat/execute", response_model=ExecuteChatResponse)
async def execute_chat(
    request: ExecuteChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Execute a chat request and get AI response."""
    try:
        # Verify session exists
        # Ensure session_id has proper table prefix
        full_session_id = _full_session_id(request.session_id)
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        await _ensure_session_access(full_session_id, user_id)

        # Determine model override (per-request override takes precedence over session-level)
        model_override = (
            request.model_override
            if request.model_override is not None
            else getattr(session, "model_override", None)
        )

        # Get current state
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        current_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Prepare state for execution
        state_values = current_state.values if current_state else {}
        state_values["messages"] = state_values.get("messages", [])
        state_values["context"] = _context_with_agent_instruction(
            request.context,
            request.agent_instruction,
        )
        state_values["model_override"] = model_override

        # Add user message to state
        from langchain_core.messages import HumanMessage

        user_message = HumanMessage(content=request.message)
        state_values["messages"].append(user_message)

        # Execute chat graph (wrapped in thread — SqliteSaver is sync).
        result = await asyncio.to_thread(
            chat_graph.invoke,
            state_values,
            RunnableConfig(
                configurable={
                    "thread_id": full_session_id,
                    "model_id": model_override,
                }
            ),
        )

        # Update session timestamp
        await session.save()

        # Convert messages to response format
        messages: list[ChatMessage] = []
        for msg in result.get("messages", []):
            messages.append(
                ChatMessage(
                    id=getattr(msg, "id", f"msg_{len(messages)}"),
                    type=msg.type if hasattr(msg, "type") else "unknown",
                    content=msg.content if hasattr(msg, "content") else str(msg),
                    timestamp=None,
                )
            )

        return ExecuteChatResponse(session_id=request.session_id, messages=messages)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        # Log detailed error with context for debugging
        logger.error(
            f"Error executing chat: {str(e)}\n"
            f"  Session ID: {request.session_id}\n"
            f"  Model override: {request.model_override}\n"
            f"  Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"Error executing chat: {str(e)}")


async def _stream_chat_sse(
    session_id: str,
    user_message: str,
    context: Dict[str, Any],
    model_override: Optional[str],
    agent_instruction: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Wrap ``astream_chat_response`` as Server-Sent Events."""
    # Echo user message first so the client can confirm receipt
    yield f"data: {json.dumps({'type': 'user_message', 'content': user_message})}\n\n"
    try:
        async for event in astream_chat_response(
            session_id=session_id,
            user_message=user_message,
            context=_context_with_agent_instruction(context, agent_instruction),
            model_override=model_override,
            prompt_template="chat/system",
        ):
            yield f"data: {json.dumps(event)}\n\n"
    except Exception as e:
        logger.error(f"Error in chat stream: {e}\n{traceback.format_exc()}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.post("/chat/execute/stream")
async def execute_chat_stream(
    request: ExecuteChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Execute a chat request with token-by-token SSE streaming."""
    full_session_id = _full_session_id(request.session_id)
    session = await ChatSession.get(full_session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _ensure_session_access(full_session_id, user_id)

    model_override = (
        request.model_override
        if request.model_override is not None
        else getattr(session, "model_override", None)
    )

    # Update session timestamp
    await session.save()

    return StreamingResponse(
        _stream_chat_sse(
            session_id=full_session_id,
            user_message=request.message,
            context=request.context,
            model_override=model_override,
            agent_instruction=request.agent_instruction,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/context", response_model=BuildContextResponse)
async def build_context(
    request: BuildContextRequest,
    navy_user_id: Optional[str] = Depends(get_navy_acl_user_id),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Build context for a notebook based on context configuration."""
    try:
        # Verify notebook exists
        notebook = await Notebook.get(request.notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        await _ensure_notebook_access(notebook, auth_user_id)

        # Precompute the caller's collaborative memberships so shared sources
        # and notes can be pulled into chat context, and derive the effective
        # navy-corpus ACL filter for collaborative notebooks.
        from api.collaboration_access import user_member_notebook_ids
        from open_notebook.collaboration import effective_navy_filter

        member_notebook_ids = await user_member_notebook_ids(auth_user_id)
        navy_acl_override = effective_navy_filter(notebook)

        context_data: dict[str, list[dict[str, str]]] = {"sources": [], "notes": []}
        total_content = ""

        # Process app sources/notes from SurrealDB. OpenSearch is reserved for
        # the external Navy corpus below, where department/clearance ACLs apply.
        if request.context_config:
            # Process sources
            for source_id, status in request.context_config.get("sources", {}).items():
                if "not in" in status:
                    continue

                try:
                    # Add table prefix if not present
                    full_source_id = (
                        source_id
                        if source_id.startswith("source:")
                        else f"source:{source_id}"
                    )

                    try:
                        source = await Source.get(full_source_id)
                    except Exception:
                        continue
                    if not source or not await _can_use_object(
                        source, auth_user_id, member_notebook_ids, "reference"
                    ):
                        continue

                    if "insights" in status or "full content" in status:
                        source_context = await _build_source_context_for_chat(
                            source, status
                        )
                        context_data["sources"].append(source_context)
                        total_content += str(source_context)
                except Exception as e:
                    logger.warning(f"Error processing source {source_id}: {str(e)}")
                    continue

            # Process notes
            for note_id, status in request.context_config.get("notes", {}).items():
                if "not in" in status:
                    continue

                try:
                    # Add table prefix if not present
                    full_note_id = (
                        note_id if note_id.startswith("note:") else f"note:{note_id}"
                    )
                    note = await Note.get(full_note_id)
                    if not note or not await _can_use_object(
                        note, auth_user_id, member_notebook_ids, "artifact"
                    ):
                        continue

                    if "full content" in status:
                        note_context = note.get_context(context_size="long")
                        context_data["notes"].append(note_context)
                        total_content += str(note_context)
                except Exception as e:
                    logger.warning(f"Error processing note {note_id}: {str(e)}")
                    continue
        else:
            # Default behavior - include all sources and notes with short context
            sources = await notebook.get_sources()
            for source in sources:
                try:
                    if not await _can_use_object(
                        source, auth_user_id, member_notebook_ids, "reference"
                    ):
                        continue
                    source_context = await source.get_context(context_size="short")
                    context_data["sources"].append(source_context)
                    total_content += str(source_context)
                except Exception as e:
                    logger.warning(f"Error processing source {source.id}: {str(e)}")
                    continue

            notes = await notebook.get_notes()
            for note in notes:
                try:
                    if not await _can_use_object(
                        note, auth_user_id, member_notebook_ids, "artifact"
                    ):
                        continue
                    note_context = note.get_context(context_size="short")
                    context_data["notes"].append(note_context)
                    total_content += str(note_context)
                except Exception as e:
                    logger.warning(f"Error processing note {note.id}: {str(e)}")
                    continue

        # Process navy corpus documents (if any selected)
        navy_config = request.context_config.get("navy_docs", {}) if request.context_config else {}
        navy_doc_ids = navy_config.get("doc_ids", [])
        if navy_doc_ids and request.query:
            try:
                # Semantic RAG: even when many doc_ids are allowed, only the
                # top-k most relevant chunks (per BGE-M3 k-NN similarity) are
                # passed to the model. Falls back to BM25 internally if the
                # query embedding cannot be generated.
                from open_notebook.search.navy_docs import (
                    vector_search_navy_documents,
                )

                # In a collaborative notebook the corpus is filtered by the
                # notebook's *effective* (most-restrictive) clearance +
                # intersected departments, so no member can surface a document
                # another member could not individually access.
                navy_kwargs: Dict[str, Any] = {}
                if navy_acl_override is not None:
                    navy_kwargs["acl_filter"] = navy_acl_override
                navy_results = await vector_search_navy_documents(
                    query=request.query,
                    doc_ids=navy_doc_ids,
                    k=5,
                    user_id=navy_user_id,
                    **navy_kwargs,
                )
                navy_context_items = []
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
                        "title": label,
                        "content": r.get("content", ""),
                    }
                    navy_context_items.append(item)
                    total_content += r.get("content", "")

                if navy_context_items:
                    context_data["navy_corpus"] = navy_context_items  # type: ignore[assignment]
                    logger.info(
                        f"Added {len(navy_context_items)} navy corpus chunks to context"
                    )
            except Exception as e:
                logger.warning(f"Error fetching navy corpus context: {e}")

        # Calculate character and token counts
        char_count = len(total_content)
        # Use token count utility if available
        try:
            from open_notebook.utils import token_count

            estimated_tokens = token_count(total_content) if total_content else 0
        except ImportError:
            # Fallback to simple estimation
            estimated_tokens = char_count // 4

        return BuildContextResponse(
            context=context_data, token_count=estimated_tokens, char_count=char_count
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building context: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error building context: {str(e)}")
