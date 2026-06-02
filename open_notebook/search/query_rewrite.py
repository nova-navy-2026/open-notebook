"""Shared query-rewrite helper (metaprompting).

A single implementation used by every retrieval flow that wants to expand a
user query into a small set of pt-PT / EN paraphrases before searching, so
recall on the multilingual navy corpus improves without each call site
re-implementing the logic.

Design goals:
- Never raise: rewriting is an enhancement, not a correctness requirement.
  On any failure the original query is returned unchanged.
- Self-contained validate-and-repair around the JSON parse.
- Opt-out via the ``QUERY_REWRITE_ENABLED`` env flag (default on).
"""
from __future__ import annotations

import os
from typing import List, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.text_utils import extract_text_content


class QueryRewrite(BaseModel):
    variants: List[str] = Field(
        default_factory=list,
        description="Alternative search queries for the same information need.",
    )


def _dedupe_preserving_order(items: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for v in items:
        if not v:
            continue
        k = v.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(v.strip())
    return out


async def rewrite_search_query(
    query: str,
    *,
    model_id: Optional[str] = None,
    instructions: str = "",
    max_variants: int = 2,
) -> List[str]:
    """Return a deduplicated list of search queries: the original plus up to
    ``max_variants`` metaprompted paraphrases. Always includes ``query`` and
    never raises.
    """
    query = (query or "").strip()
    if not query:
        return []
    if os.environ.get("QUERY_REWRITE_ENABLED", "true").lower() == "false" or max_variants <= 0:
        return [query]

    try:
        parser = PydanticOutputParser(pydantic_object=QueryRewrite)
        payload = {
            "question": query,
            "term": query,
            "instructions": instructions,
            "max_variants": max_variants,
        }
        system_prompt = Prompter(
            prompt_template="ask/query_rewrite", parser=parser
        ).render(data=payload)  # type: ignore[arg-type]
        model = await provision_langchain_model(
            system_prompt,
            model_id,
            "tools",
            max_tokens=400,
            structured=dict(type="json"),
        )
        ai_message = await model.ainvoke(system_prompt)
        cleaned = clean_thinking_content(extract_text_content(ai_message.content))

        try:
            rewrite = parser.parse(cleaned)
        except Exception as parse_err:
            # One-shot validate-and-repair: feed the parse error back.
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
            rewrite = parser.parse(cleaned)

        variants = _dedupe_preserving_order([query] + list(rewrite.variants or []))
        return variants[: max_variants + 1]
    except Exception as e:
        logger.warning(f"Query rewrite failed, using original query: {e}")
        return [query]
