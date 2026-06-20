import importlib
import pkgutil
from functools import lru_cache
from typing import Dict, Iterable, List, Optional

from loguru import logger

from api.chat_agents.base import ChatAgentDefinition
from api.chat_agents import agents


@lru_cache(maxsize=1)
def get_agent_registry() -> Dict[str, ChatAgentDefinition]:
    registry: Dict[str, ChatAgentDefinition] = {}
    for module_info in pkgutil.iter_modules(agents.__path__, agents.__name__ + "."):
        module = importlib.import_module(module_info.name)
        agent = getattr(module, "AGENT", None)
        if isinstance(agent, ChatAgentDefinition):
            registry[agent.name] = agent
    return dict(sorted(registry.items()))


def list_agents() -> List[ChatAgentDefinition]:
    return list(get_agent_registry().values())


def get_agent(name: Optional[str]) -> Optional[ChatAgentDefinition]:
    if not name:
        return None
    return get_agent_registry().get(str(name).strip().lower())


def normalise_agent_name(raw: object) -> str:
    agent = str(raw or "normal_chat").strip().lower()
    if agent not in get_agent_registry():
        logger.warning(
            "ChatAgent router returned unknown agent name {!r}; falling back to normal_chat. "
            "Known agents: {}",
            agent,
            list(get_agent_registry().keys()),
        )
        return "normal_chat"
    return agent


def agent_names_for_prompt() -> str:
    return "|".join(get_agent_registry().keys())


def agent_catalog_for_prompt() -> str:
    lines: List[str] = []
    for agent in list_agents():
        lines.append(f"- {agent.name}: {agent.description}")
        if agent.routing_guidance:
            lines.append(f"  Guidance: {agent.routing_guidance}")
    return "\n".join(lines)


def parameters_for_prompt() -> str:
    params: Dict[str, str] = {}
    for agent in list_agents():
        params.update(agent.parameters)
    if not params:
        return "{}"
    lines = ["{"]
    for key, description in sorted(params.items()):
        lines.append(f'  "{key}": "{description}",')
    lines.append("}")
    return "\n".join(lines)


def agents_for_file_type(file_type: str) -> Iterable[ChatAgentDefinition]:
    file_type = (file_type or "").lower()
    for agent in list_agents():
        if any(file_type.startswith(prefix) for prefix in agent.file_type_prefixes):
            yield agent

