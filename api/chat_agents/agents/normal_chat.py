from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="normal_chat",
    handler="normal_chat",
    description="Pergunta geral, conversa, explicação, ou RAG normal.",
    routing_guidance="Usa quando a intenção é ambígua ou não precisa de uma ferramenta específica.",
)

