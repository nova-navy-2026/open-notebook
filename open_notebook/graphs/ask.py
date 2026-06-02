import asyncio
import operator
from typing import Annotated, List

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.notebook import vector_search
from open_notebook.exceptions import OpenNotebookError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


class SubGraphState(TypedDict):
    question: str
    term: str
    instructions: str
    results: dict
    answer: str
    ids: list  # Added for provide_answer function


class Search(BaseModel):
    term: str
    instructions: str = Field(
        description="Tell the answeting LLM what information you need extracted from this search"
    )


class Strategy(BaseModel):
    reasoning: str
    searches: List[Search] = Field(
        default_factory=list,
        description="You can add up to five searches to this strategy",
    )


class ThreadState(TypedDict):
    question: str
    strategy: Strategy
    answers: Annotated[list, operator.add]
    final_answer: str
    unsupported_issues: List[str]


class Verification(BaseModel):
    supported: bool = Field(
        description="True if the final answer is fully grounded in the sub-answers."
    )
    issues: List[str] = Field(
        default_factory=list,
        description="Concrete unsupported claims, fabricated IDs, or missing caveats.",
    )
    revised_answer: str = Field(
        default="",
        description="Grounded answer. If supported is true, this may be empty or equal to the current final answer.",
    )


async def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        parser = PydanticOutputParser(pydantic_object=Strategy)
        system_prompt = Prompter(prompt_template="ask/entry", parser=parser).render(  # type: ignore[arg-type]
            data=state  # type: ignore[arg-type]
        )
        model = await provision_langchain_model(
            system_prompt,
            config.get("configurable", {}).get("strategy_model"),
            "tools",
            max_tokens=2000,
            structured=dict(type="json"),
        )
        # model = model.bind_tools(tools)
        # First get the raw response from the model
        ai_message = await model.ainvoke(system_prompt)

        # Clean the thinking content from the response
        message_content = extract_text_content(ai_message.content)
        cleaned_content = clean_thinking_content(message_content)

        try:
            strategy = parser.parse(cleaned_content)
        except Exception as parse_err:
            # One-shot validate-and-repair: feed the parse error back so the
            # model can fix its own malformed JSON without failing the run.
            repair_prompt = (
                f"{system_prompt}\n\n"
                "# PREVIOUS RESPONSE (invalid)\n"
                f"{cleaned_content}\n\n"
                "# PARSER ERROR\n"
                f"{parse_err}\n\n"
                "Return a corrected JSON object that matches the schema. "
                "Output only the JSON, no commentary, no markdown."
            )
            ai_message = await model.ainvoke(repair_prompt)
            cleaned_content = clean_thinking_content(
                extract_text_content(ai_message.content)
            )
            strategy = parser.parse(cleaned_content)

        return {"strategy": strategy}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


async def trigger_queries(state: ThreadState, config: RunnableConfig):
    return [
        Send(
            "provide_answer",
            {
                "question": state["question"],
                "instructions": s.instructions,
                "term": s.term,
                # "type": s.type,
            },
        )
        for s in state["strategy"].searches
    ]


async def _rewrite_query(
    question: str,
    term: str,
    instructions: str,
    config: RunnableConfig,
    max_variants: int = 2,
) -> List[str]:
    """Metaprompting: expand the current search term into retrieval-friendly
    variants. Delegates to the shared ``rewrite_search_query`` helper so the
    same implementation is used across every retrieval flow. Never raises.
    """
    from open_notebook.search.query_rewrite import rewrite_search_query

    model_id = config.get("configurable", {}).get(
        "query_rewrite_model"
    ) or config.get("configurable", {}).get("strategy_model")
    # The shared helper keys off the query text; pass the term as the query and
    # forward the per-search extraction instructions for better paraphrases.
    instructions = f"{instructions}\n\nOriginal question: {question}".strip()
    return await rewrite_search_query(
        term,
        model_id=model_id,
        instructions=instructions,
        max_variants=max_variants,
    )


async def provide_answer(state: SubGraphState, config: RunnableConfig) -> dict:
    try:
        payload = state
        term = state["term"]

        # Metaprompting: rewrite the search term into a small set of variants
        # (original + pt-PT/EN paraphrases) and merge the retrieved hits.
        # Improves recall on a multilingual corpus without changing downstream
        # nodes.
        variants = await _rewrite_query(
            question=state["question"],
            term=term,
            instructions=state.get("instructions", ""),
            config=config,
        )

        merged: dict = {}
        per_query = max(3, 10 // max(1, len(variants)))

        async def _search(v: str):
            try:
                return await vector_search(v, per_query, True, True)
            except Exception:
                return []

        # Run variant retrievals in parallel; preserve original order when
        # merging so the original term's hits win ties on deduplication.
        all_hits = await asyncio.gather(*(_search(v) for v in variants))
        for hits in all_hits:
            for r in hits:
                rid = r.get("id")
                if rid and rid not in merged:
                    merged[rid] = r

        results = list(merged.values())[:10]
        if len(results) == 0:
            return {"answers": []}
        payload["results"] = results
        ids = [r["id"] for r in results]
        payload["ids"] = ids
        system_prompt = Prompter(prompt_template="ask/query_process").render(data=payload)  # type: ignore[arg-type]
        model = await provision_langchain_model(
            system_prompt,
            config.get("configurable", {}).get("answer_model"),
            "tools",
            max_tokens=2000,
        )
        ai_message = await model.ainvoke(system_prompt)
        ai_content = extract_text_content(ai_message.content)
        return {"answers": [clean_thinking_content(ai_content)]}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


async def write_final_answer(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        system_prompt = Prompter(prompt_template="ask/final_answer").render(data=state)  # type: ignore[arg-type]
        model = await provision_langchain_model(
            system_prompt,
            config.get("configurable", {}).get("final_answer_model"),
            "tools",
            max_tokens=2000,
        )
        ai_message = await model.ainvoke(system_prompt)
        final_content = extract_text_content(ai_message.content)
        return {"final_answer": clean_thinking_content(final_content)}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


async def verify_answer(state: ThreadState, config: RunnableConfig) -> dict:
    """Iterative self-check: verify the final answer against the sub-answers
    and revise it once if unsupported claims are detected.

    Bounded to a single pass to keep cost predictable. Falls back to the
    original answer if verification itself fails, so this node never breaks
    the graph.
    """
    try:
        if not state.get("final_answer") or not state.get("answers"):
            return {}

        parser = PydanticOutputParser(pydantic_object=Verification)
        system_prompt = Prompter(prompt_template="ask/verify", parser=parser).render(  # type: ignore[arg-type]
            data=state  # type: ignore[arg-type]
        )
        model = await provision_langchain_model(
            system_prompt,
            config.get("configurable", {}).get("verify_model")
            or config.get("configurable", {}).get("final_answer_model"),
            "tools",
            max_tokens=2000,
            structured=dict(type="json"),
        )
        ai_message = await model.ainvoke(system_prompt)
        cleaned = clean_thinking_content(extract_text_content(ai_message.content))

        try:
            verification = parser.parse(cleaned)
        except Exception as parse_err:
            repair_prompt = (
                f"{system_prompt}\n\n"
                "# PREVIOUS RESPONSE (invalid)\n"
                f"{cleaned}\n\n"
                "# PARSER ERROR\n"
                f"{parse_err}\n\n"
                "Return a corrected JSON object that matches the schema. "
                "Output only the JSON, no commentary, no markdown."
            )
            ai_message = await model.ainvoke(repair_prompt)
            cleaned = clean_thinking_content(extract_text_content(ai_message.content))
            verification = parser.parse(cleaned)

        if verification.supported:
            return {"unsupported_issues": []}

        revised = (verification.revised_answer or "").strip()

        # Persist the failure as a learning signal for the prompt-improvement
        # loop. Best-effort; never blocks the response.
        try:
            from open_notebook.improvement import record_failure

            record_failure(
                question=state.get("question", ""),
                original_answer=state.get("final_answer", ""),
                revised_answer=revised or None,
                issues=verification.issues,
                sub_answers=state.get("answers"),
            )
        except Exception:
            pass

        if not revised:
            return {"unsupported_issues": verification.issues}

        return {
            "final_answer": revised,
            "unsupported_issues": verification.issues,
        }
    except OpenNotebookError:
        raise
    except Exception:
        # Verification is an enhancement; never let it break the run.
        return {}


agent_state = StateGraph(ThreadState)
agent_state.add_node("agent", call_model_with_messages)
agent_state.add_node("provide_answer", provide_answer)
agent_state.add_node("write_final_answer", write_final_answer)
agent_state.add_node("verify_answer", verify_answer)
agent_state.add_edge(START, "agent")
agent_state.add_conditional_edges("agent", trigger_queries, ["provide_answer"])
agent_state.add_edge("provide_answer", "write_final_answer")
agent_state.add_edge("write_final_answer", "verify_answer")
agent_state.add_edge("verify_answer", END)

graph = agent_state.compile()
