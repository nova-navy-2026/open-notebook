import asyncio
from typing import Annotated, Any, AsyncGenerator, Optional

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.notebook import Notebook
from open_notebook.exceptions import OpenNotebookError
from open_notebook.graphs.checkpoint import checkpointer
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.chat_compress import compress_chat_history, compress_checkpoint_if_needed
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


class ThreadState(TypedDict):
    messages: Annotated[list, add_messages]
    notebook: Optional[Notebook]
    context: Optional[str]
    context_config: Optional[dict]
    model_override: Optional[str]
    prompt_template: Optional[str]
    # Human-readable name of the app's UI language (e.g. "English"). Used as a
    # secondary preference for the reply language when the user's message
    # language is ambiguous. See the LANGUAGE rule in the chat system prompts.
    app_language: Optional[str]


def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        template = state.get("prompt_template") or "chat/system"
        system_prompt = Prompter(prompt_template=template).render(data=state)  # type: ignore[arg-type]
        payload = [SystemMessage(content=system_prompt)] + state.get("messages", [])
        model_id = config.get("configurable", {}).get("model_id") or state.get(
            "model_override"
        )

        def run_in_new_loop():
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                return new_loop.run_until_complete(
                    provision_langchain_model(
                        str(payload), model_id, "chat", max_tokens=8192
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
                    model_id,
                    "chat",
                    max_tokens=8192,
                )
            )

        ai_message = model.invoke(payload)

        content = extract_text_content(ai_message.content)
        cleaned_content = clean_thinking_content(content)
        cleaned_message = ai_message.model_copy(update={"content": cleaned_content})

        return {"messages": cleaned_message}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


agent_state = StateGraph(ThreadState)
agent_state.add_node("agent", call_model_with_messages)
agent_state.add_edge(START, "agent")
agent_state.add_edge("agent", END)
graph = agent_state.compile(checkpointer=checkpointer)


async def astream_chat_response(
    session_id: str,
    user_message: str,
    context: Optional[Any] = None,
    model_override: Optional[str] = None,
    prompt_template: str = "chat/system",
    app_language: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    """Stream an LLM response token-by-token for the given chat session.

    Yields dict events:
      - {"type": "delta", "content": <chunk>}
      - {"type": "complete", "content": <full text>}
      - {"type": "error", "message": <user-facing message>}

    On success, persists the human + AI messages to the LangGraph checkpoint and
    then durably compresses the checkpoint if it has grown beyond the token budget.
    """
    try:
        config = RunnableConfig(configurable={"thread_id": session_id})

        current_state = await asyncio.to_thread(graph.get_state, config=config)
        existing_messages = []
        if current_state and current_state.values:
            existing_messages = current_state.values.get("messages", [])

        human_msg = HumanMessage(content=user_message)
        all_messages = existing_messages + [human_msg]

        # In-memory compression for this LLM call only.
        compressed_messages = await compress_chat_history(
            all_messages, model_id=model_override
        )

        prompt_state = {
            "messages": compressed_messages,
            "context": context,
            "model_override": model_override,
            "prompt_template": prompt_template,
            "app_language": app_language,
        }

        system_prompt = Prompter(prompt_template=prompt_template).render(
            data=prompt_state  # type: ignore[arg-type]
        )
        payload = [SystemMessage(content=system_prompt)] + prompt_state["messages"]

        model = await provision_langchain_model(
            str(payload), model_override, "chat", max_tokens=8192
        )

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

        # Persist to checkpoint (add_messages reducer appends).
        ai_message = AIMessage(content=cleaned)
        await asyncio.to_thread(
            graph.update_state,
            config,
            {"messages": [human_msg, ai_message]},
        )

        yield {"type": "complete", "content": cleaned}

        # Durably compress the checkpoint if it has grown too large.
        await compress_checkpoint_if_needed(graph, config, model_id=model_override)

    except OpenNotebookError as e:
        yield {"type": "error", "message": str(e)}
    except Exception as e:
        _, user_facing = classify_error(e)
        yield {"type": "error", "message": user_facing}
