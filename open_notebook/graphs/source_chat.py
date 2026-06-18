import asyncio
from typing import Annotated, AsyncGenerator, Dict, List, Optional

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.notebook import Source, SourceInsight
from open_notebook.exceptions import OpenNotebookError
from open_notebook.graphs.checkpoint import checkpointer
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.chat_compress import compress_chat_history, compress_checkpoint_if_needed
from open_notebook.utils.context_builder import ContextBuilder
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


class SourceChatState(TypedDict):
    messages: Annotated[list, add_messages]
    source_id: str
    source: Optional[Source]
    insights: Optional[List[SourceInsight]]
    context: Optional[str]
    model_override: Optional[str]
    context_indicators: Optional[Dict[str, List[str]]]


def call_model_with_source_context(
    state: SourceChatState, config: RunnableConfig
) -> dict:
    try:
        return _call_model_with_source_context_inner(state, config)
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


def _call_model_with_source_context_inner(
    state: SourceChatState, config: RunnableConfig
) -> dict:
    source_id = state.get("source_id")
    if not source_id:
        raise ValueError("source_id is required in state")

    def build_context():
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            context_builder = ContextBuilder(
                source_id=source_id,
                include_insights=True,
                include_notes=False,
                max_tokens=50000,
            )
            return new_loop.run_until_complete(context_builder.build())
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(build_context)
            context_data = future.result()
    except RuntimeError:
        context_data = build_context()

    source = None
    insights = []
    context_indicators: dict[str, list[str | None]] = {
        "sources": [],
        "insights": [],
        "notes": [],
    }

    if context_data.get("sources"):
        source_info = context_data["sources"][0]
        source = Source(**source_info) if isinstance(source_info, dict) else source_info
        context_indicators["sources"].append(source.id)

    if context_data.get("insights"):
        for insight_data in context_data["insights"]:
            insight = (
                SourceInsight(**insight_data)
                if isinstance(insight_data, dict)
                else insight_data
            )
            insights.append(insight)
            context_indicators["insights"].append(insight.id)

    formatted_context = _format_source_context(context_data)

    prompt_data = {
        "source": source.model_dump() if source else None,
        "insights": [insight.model_dump() for insight in insights] if insights else [],
        "context": formatted_context,
        "context_indicators": context_indicators,
    }

    system_prompt = Prompter(prompt_template="source_chat/system").render(
        data=prompt_data
    )
    payload = [SystemMessage(content=system_prompt)] + state.get("messages", [])

    def run_in_new_loop():
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(
                provision_langchain_model(
                    str(payload),
                    config.get("configurable", {}).get("model_id")
                    or state.get("model_override"),
                    "chat",
                    max_tokens=8192,
                )
            )
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_new_loop)
            model = future.result()
    except RuntimeError:
        model = asyncio.run(
            provision_langchain_model(
                str(payload),
                config.get("configurable", {}).get("model_id")
                or state.get("model_override"),
                "chat",
                max_tokens=8192,
            )
        )

    ai_message = model.invoke(payload)

    content = extract_text_content(ai_message.content)
    cleaned_content = clean_thinking_content(content)
    cleaned_message = ai_message.model_copy(update={"content": cleaned_content})

    return {
        "messages": cleaned_message,
        "source": source,
        "insights": insights,
        "context": formatted_context,
        "context_indicators": context_indicators,
    }


def _format_source_context(context_data: Dict) -> str:
    """Format context data from ContextBuilder into a prompt-ready string.

    No hard character cap is applied here — ContextBuilder already enforces a
    token budget when loading content from the database.
    """
    context_parts = []

    if context_data.get("sources"):
        context_parts.append("## SOURCE CONTENT")
        for source in context_data["sources"]:
            if isinstance(source, dict):
                context_parts.append(f"**Source ID:** {source.get('id', 'Unknown')}")
                context_parts.append(f"**Title:** {source.get('title', 'No title')}")
                if source.get("full_text"):
                    context_parts.append(f"**Content:**\n{source['full_text']}")
                context_parts.append("")

    if context_data.get("insights"):
        context_parts.append("## SOURCE INSIGHTS")
        for insight in context_data["insights"]:
            if isinstance(insight, dict):
                context_parts.append(f"**Insight ID:** {insight.get('id', 'Unknown')}")
                context_parts.append(
                    f"**Type:** {insight.get('insight_type', 'Unknown')}"
                )
                context_parts.append(
                    f"**Content:** {insight.get('content', 'No content')}"
                )
                context_parts.append("")

    if context_data.get("metadata"):
        metadata = context_data["metadata"]
        context_parts.append("## CONTEXT METADATA")
        context_parts.append(f"- Source count: {metadata.get('source_count', 0)}")
        context_parts.append(f"- Insight count: {metadata.get('insight_count', 0)}")
        context_parts.append(f"- Total tokens: {context_data.get('total_tokens', 0)}")
        context_parts.append("")

    return "\n".join(context_parts)


source_chat_state = StateGraph(SourceChatState)
source_chat_state.add_node("source_chat_agent", call_model_with_source_context)
source_chat_state.add_edge(START, "source_chat_agent")
source_chat_state.add_edge("source_chat_agent", END)
source_chat_graph = source_chat_state.compile(checkpointer=checkpointer)


async def astream_source_chat_response(
    session_id: str,
    source_id: str,
    user_message: str,
    model_override: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    """Stream a source-chat LLM response token-by-token.

    Builds source context asynchronously, compresses in-memory history for the
    LLM call, then streams tokens and persists the exchange to the checkpoint.
    After persisting, durably compresses the checkpoint if it exceeds the budget.

    Yields same event schema as astream_chat_response:
      - {"type": "delta", "content": <chunk>}
      - {"type": "context_indicators", "data": {...}}
      - {"type": "complete", "content": <full text>}
      - {"type": "error", "message": <user-facing message>}
    """
    try:
        config = RunnableConfig(configurable={"thread_id": session_id})

        # Build source context asynchronously — no thread-in-thread overhead.
        context_builder = ContextBuilder(
            source_id=source_id,
            include_insights=True,
            include_notes=False,
            max_tokens=50000,
        )
        context_data = await context_builder.build()

        # Extract source, insights, and context indicators.
        source = None
        insights: list[SourceInsight] = []
        context_indicators: Dict[str, List[str]] = {
            "sources": [],
            "insights": [],
            "notes": [],
        }

        if context_data.get("sources"):
            source_info = context_data["sources"][0]
            source = (
                Source(**source_info) if isinstance(source_info, dict) else source_info
            )
            if source.id:
                context_indicators["sources"].append(source.id)

        if context_data.get("insights"):
            for insight_data in context_data["insights"]:
                insight = (
                    SourceInsight(**insight_data)
                    if isinstance(insight_data, dict)
                    else insight_data
                )
                insights.append(insight)
                if insight.id:
                    context_indicators["insights"].append(insight.id)

        formatted_context = _format_source_context(context_data)

        # Load existing checkpoint messages.
        current_state = await asyncio.to_thread(
            source_chat_graph.get_state, config=config
        )
        existing_messages = []
        if current_state and current_state.values:
            existing_messages = current_state.values.get("messages", [])

        human_msg = HumanMessage(content=user_message)
        all_messages = existing_messages + [human_msg]

        # In-memory compression for this LLM call only.
        compressed_messages = await compress_chat_history(
            all_messages, model_id=model_override
        )

        # Build system prompt.
        prompt_data = {
            "source": source.model_dump() if source else None,
            "insights": [i.model_dump() for i in insights],
            "context": formatted_context,
            "context_indicators": context_indicators,
        }
        system_prompt = Prompter(prompt_template="source_chat/system").render(
            data=prompt_data
        )
        payload = [SystemMessage(content=system_prompt)] + compressed_messages

        # Provision model.
        model = await provision_langchain_model(
            str(payload), model_override, "chat", max_tokens=8192
        )

        # Stream tokens.
        full_text_parts: list[str] = []
        try:
            async for chunk in model.astream(payload):
                content = extract_text_content(getattr(chunk, "content", ""))
                if content:
                    full_text_parts.append(content)
                    yield {"type": "delta", "content": content}
        except NotImplementedError:
            ai = await asyncio.to_thread(model.invoke, payload)
            content = extract_text_content(getattr(ai, "content", ""))
            full_text_parts.append(content)
            yield {"type": "delta", "content": content}

        full_text = "".join(full_text_parts)
        cleaned = clean_thinking_content(full_text)

        # Persist human + AI messages and context indicators to checkpoint.
        ai_message = AIMessage(content=cleaned)
        await asyncio.to_thread(
            source_chat_graph.update_state,
            config,
            {
                "messages": [human_msg, ai_message],
                "context_indicators": context_indicators,
            },
        )

        yield {"type": "context_indicators", "data": context_indicators}
        yield {"type": "complete", "content": cleaned}

        # Durably compress the checkpoint if it has grown too large.
        await compress_checkpoint_if_needed(
            source_chat_graph, config, model_id=model_override
        )

    except OpenNotebookError as e:
        yield {"type": "error", "message": str(e)}
    except Exception as e:
        _, user_facing = classify_error(e)
        yield {"type": "error", "message": user_facing}
