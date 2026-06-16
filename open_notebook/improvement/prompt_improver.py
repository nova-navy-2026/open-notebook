"""Metaprompting: use accumulated verification failures to propose an
improved version of `prompts/ask/final_answer.jinja`.

The proposal is written next to the original as
`prompts/ask/final_answer.suggested.jinja` and is NEVER auto-applied. A
human reviews the diff and decides whether to promote it.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.improvement import read_failures
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.text_utils import extract_text_content

# Resolve repo-relative prompts/ folder regardless of CWD.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir, os.pardir))
PROMPTS_DIR = os.path.join(_REPO_ROOT, "prompts")

TARGET_TEMPLATE_REL = os.path.join("ask", "final_answer.jinja")
SUGGESTED_TEMPLATE_REL = os.path.join("ask", "final_answer.suggested.jinja")


def _summarise_failures(records: List[Dict[str, Any]], max_chars: int = 6000) -> str:
    """Compact rendering of failure records for the meta-LLM."""
    chunks: List[str] = []
    for i, r in enumerate(records, 1):
        issues = "; ".join(r.get("issues") or []) or "(no issues listed)"
        original = (r.get("original_answer") or "").strip()
        revised = (r.get("revised_answer") or "").strip()
        block = (
            f"--- Failure {i} ---\n"
            f"Question: {r.get('question', '')}\n"
            f"Issues: {issues}\n"
            f"Original answer (truncated):\n{original[:600]}\n"
            f"Revised answer (truncated):\n{revised[:600]}\n"
        )
        chunks.append(block)
    text = "\n".join(chunks)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated] ..."
    return text


META_INSTRUCTIONS = """# ROLE
You are a prompt engineer. Rewrite the CURRENT PROMPT below so that the
listed FAILURES become less likely in future runs.

# WHAT TO IMPROVE
The current prompt is used as the final-synthesis step of a document-search
workflow. The verifier flagged the failures below because the synthesised
answer introduced claims, citation IDs, or details that were not present in
the sub-answers.

Rewrite the prompt so it more strongly enforces:
- Grounding: every factual claim must come from the sub-answers.
- Citation discipline: only use citation IDs that already appear in the
  sub-answers; never invent IDs or cite filenames/URLs.
- Language: default European Portuguese (pt-PT), switch only if the user's
  question is clearly in another language. If writing Portuguese, enforce
  European Portuguese and avoid Brazilian Portuguese forms.
- No meta commentary, no references section.
- Explicitly state when evidence is incomplete instead of guessing.

# CONSTRAINTS
- Keep ALL existing Jinja placeholders (e.g. {{question}}, {{strategy}},
  {{answers}}). Do not rename or remove them.
- Keep the overall structure (sections like # ROLE, # TASK, # RULES).
- Output ONLY the rewritten Jinja template content, nothing else. No
  markdown fences, no commentary, no preface.

# CURRENT PROMPT
{current_prompt}

# RECENT FAILURES
{failures}
"""


async def propose_improved_final_answer_prompt(
    failure_limit: int = 30,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Read recent verification failures and write an improved-prompt proposal.

    Returns a dict with `status` and metadata. Never modifies the live
    template; writes to a `.suggested.jinja` sibling for human review.
    """
    failures = read_failures(limit=failure_limit)
    if not failures:
        return {
            "status": "skipped",
            "reason": "no verification failures recorded yet",
            "failure_count": 0,
        }

    target_path = os.path.join(PROMPTS_DIR, TARGET_TEMPLATE_REL)
    if not os.path.exists(target_path):
        return {
            "status": "error",
            "reason": f"target template not found: {target_path}",
        }

    with open(target_path, "r", encoding="utf-8") as fh:
        current_prompt = fh.read()

    meta_prompt = META_INSTRUCTIONS.format(
        current_prompt=current_prompt,
        failures=_summarise_failures(failures),
    )

    try:
        model = await provision_langchain_model(
            meta_prompt,
            model_id,
            "tools",
            max_tokens=3000,
        )
        ai_message = await model.ainvoke(meta_prompt)
        proposal = clean_thinking_content(extract_text_content(ai_message.content)).strip()
    except Exception as e:
        logger.error(f"Prompt improvement meta-call failed: {e}")
        return {"status": "error", "reason": str(e)}

    # Strip accidental markdown fences if the model added them.
    if proposal.startswith("```"):
        lines = proposal.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        proposal = "\n".join(lines).strip()

    # Sanity check: required placeholders must survive the rewrite.
    required = ["{{question}}", "{{strategy}}", "{{answers}}"]
    missing = [p for p in required if p not in proposal]
    if missing:
        return {
            "status": "rejected",
            "reason": f"proposal missing required placeholders: {missing}",
            "preview": proposal[:400],
        }

    suggested_path = os.path.join(PROMPTS_DIR, SUGGESTED_TEMPLATE_REL)
    header = (
        "{# Auto-generated proposal from open_notebook.improvement.prompt_improver\n"
        f" # generated_at: {datetime.now(timezone.utc).isoformat()}\n"
        f" # based_on_failures: {len(failures)}\n"
        " # Review the diff vs final_answer.jinja before promoting. #}\n\n"
    )
    with open(suggested_path, "w", encoding="utf-8") as fh:
        fh.write(header + proposal + ("\n" if not proposal.endswith("\n") else ""))

    return {
        "status": "proposal_written",
        "failure_count": len(failures),
        "target": TARGET_TEMPLATE_REL,
        "suggested": SUGGESTED_TEMPLATE_REL,
        "suggested_path": suggested_path,
    }
