from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="checklist_procedure",
    handler="text_instruction",
    description="Criar checklist, procedimento ou passos operacionais.",
    routing_guidance="Usa para pedidos de checklist, procedimento, instruções, passos ou sequência operacional.",
    instruction=(
        "[Modo agente: Checklist/Procedimento]\n"
        "Transforma a resposta num procedimento operacional claro. Usa passos numerados, "
        "pré-condições, verificações, riscos/atenções e resultado esperado. Mantém pt-PT."
    ),
    fallback_keywords=("checklist", "procedimento", "procedimentos", "procedure", "passos", "steps", "instruções", "instrucoes"),
)

