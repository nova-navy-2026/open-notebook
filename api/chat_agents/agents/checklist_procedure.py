from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="checklist_procedure",
    handler="text_instruction",
    description="Criar checklist, procedimento, protocolo ou lista de verificação operacional.",
    routing_guidance="Usa para pedidos de checklist, procedimento, protocolo, instruções, passos, sequência operacional ou lista de verificação.",
    instruction=(
        "[Modo agente: Checklist/Procedimento]\n"
        "Transforma a resposta num procedimento operacional claro. Usa passos numerados, "
        "pré-condições, verificações, riscos/atenções e resultado esperado. Mantém pt-PT."
    ),
    fallback_keywords=(
        "checklist", "procedimento", "procedimentos", "procedure",
        "passos", "steps", "instrucoes", "instrucao",
        "protocolo", "protocolos",
        "lista de verificacao", "lista de passos",
        "sequencia de passos", "guia operacional",
        "roteiro", "como executar", "como realizar",
    ),
)

