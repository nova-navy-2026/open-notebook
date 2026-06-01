"""Admin endpoints for prompt self-improvement (metaprompting).

These endpoints expose the verification-failure log and a way to trigger
the meta-LLM proposal that suggests an improved `ask/final_answer.jinja`.
Proposals are written to disk as `*.suggested.jinja` and never auto-applied.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth import get_current_user_id, is_admin
from open_notebook.improvement import read_failures
from open_notebook.improvement.prompt_improver import (
    propose_improved_final_answer_prompt,
)

router = APIRouter(prefix="/prompt-improvement", tags=["prompt-improvement"])


def _require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin role required")


@router.get("/failures")
async def list_verify_failures(
    request: Request,
    limit: int = 50,
    _user_id: str = Depends(get_current_user_id),
):
    """Return the most recent verification failures recorded by the /ask
    self-check node. Admin only."""
    _require_admin(request)
    records = read_failures(limit=limit)
    return {"count": len(records), "records": records}


@router.post("/propose-final-answer-prompt")
async def propose_final_answer_prompt(
    request: Request,
    failure_limit: int = 30,
    model_id: Optional[str] = None,
    _user_id: str = Depends(get_current_user_id),
):
    """Run the metaprompting loop: read recent verification failures and
    write an improved `prompts/ask/final_answer.suggested.jinja` next to the
    live template. The proposal is NEVER auto-applied. Admin only."""
    _require_admin(request)
    result = await propose_improved_final_answer_prompt(
        failure_limit=failure_limit,
        model_id=model_id,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("reason", "unknown error"))
    return result
