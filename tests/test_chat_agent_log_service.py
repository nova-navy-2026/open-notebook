import json

import pytest

from api.chat_agent_log_service import build_chat_agent_event, write_chat_agent_event


@pytest.mark.asyncio
async def test_write_chat_agent_event_jsonl(monkeypatch, tmp_path):
    log_file = tmp_path / "chat-agent-events.jsonl"
    monkeypatch.setenv("CHAT_AGENT_TOOL_LOG_FILE", str(log_file))

    event = build_chat_agent_event(
        source="frontend",
        user_id="user:test",
        surface="global_chat",
        run_id="global_chat:test-run",
        session_id="chat_session:test",
        agent="route",
        event="tool_call",
        status="success",
        message_preview="rota de Lisboa para Porto",
        duration_ms=42,
        details={"distance_km": 313.2},
    )

    written = await write_chat_agent_event(event)

    assert written is True
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["schema_version"] == 1
    assert payload["source"] == "frontend"
    assert payload["surface"] == "global_chat"
    assert payload["run_id"] == "global_chat:test-run"
    assert payload["session_id"] == "chat_session:test"
    assert payload["agent"] == "route"
    assert payload["event"] == "tool_call"
    assert payload["status"] == "success"
    assert payload["details"]["distance_km"] == 313.2
