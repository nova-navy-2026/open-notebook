from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ChatAgentDefinition:
    """Declarative metadata used by the Gemma chat-agent router."""

    name: str
    description: str
    routing_guidance: str
    handler: str = "normal_chat"
    instruction: Optional[str] = None
    parameters: Dict[str, str] = field(default_factory=dict)
    fallback_keywords: tuple[str, ...] = ()
    file_type_prefixes: tuple[str, ...] = ()


def make_agent(**kwargs: Any) -> ChatAgentDefinition:
    return ChatAgentDefinition(**kwargs)

