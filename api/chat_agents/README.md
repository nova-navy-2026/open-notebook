# Chat Agents

Each chat-agent visible to the Gemma router is defined as a Python file in
`api/chat_agents/agents/`.

To add a prompt-only agent:

1. Create `api/chat_agents/agents/my_agent.py`.
2. Export `AGENT = make_agent(...)`.
3. Set `handler="text_instruction"` and provide `instruction=...`.
4. Restart the API.

Prompt-only agents do not need frontend changes because the router response
returns the instruction to the existing chat flow.

Tool agents may still need frontend/backend execution code when they call a new
API or require custom controls.

Example:

```python
from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="my_agent",
    handler="text_instruction",
    description="Short description used in the router prompt.",
    routing_guidance="When Gemma should select this agent.",
    instruction="[Modo agente: My Agent]\nStructure the answer like this...",
    fallback_keywords=("keyword",),
)
```
