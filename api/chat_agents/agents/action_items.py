from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="action_items",
    handler="text_instruction",
    description="Extrair ações, tarefas, decisões ou responsabilidades de documentos, reuniões ou conversas.",
    routing_guidance=(
        "Usa quando o utilizador quer extrair o que ficou para fazer, tarefas pendentes, "
        "responsáveis, prazos, decisões tomadas ou pontos de ação de um texto ou reunião."
    ),
    instruction=(
        "[Modo agente: Pontos de ação]\n"
        "Extrai e lista todos os pontos de ação, tarefas e decisões. "
        "Para cada item indica: ação, responsável (se identificável), prazo (se mencionado), "
        "prioridade relativa e fonte/evidência curta. "
        "Separa ações concretas de recomendações genéricas. Usa pt-PT."
    ),
    fallback_keywords=(
        "pontos de acao", "action items", "tarefas",
        "o que ficou para fazer", "o que fazer",
        "proximos passos", "next steps",
        "decisoes", "decisoes tomadas",
        "responsaveis", "quem faz o que",
        "pendentes", "pendencias",
        "follow-up", "followup",
    ),
)
