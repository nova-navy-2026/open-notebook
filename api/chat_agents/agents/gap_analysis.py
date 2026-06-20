from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="gap_analysis",
    handler="text_instruction",
    description="Identificar lacunas, informação em falta, contradições ou pontos por clarificar nos documentos disponíveis.",
    routing_guidance=(
        "Usa quando o utilizador quer saber o que falta, o que não está coberto, "
        "contradições, inconsistências, informação insuficiente ou áreas por investigar "
        "no contexto disponível."
    ),
    instruction=(
        "[Modo agente: Análise de lacunas]\n"
        "Analisa criticamente o material disponível. Identifica e categoriza: "
        "informação ausente (o que devia estar mas não está), "
        "contradições entre fontes, afirmações sem suporte, "
        "áreas com cobertura insuficiente e questões por responder. "
        "Para cada lacuna indica a relevância e o impacto. Usa pt-PT."
    ),
    fallback_keywords=(
        "lacunas", "lacuna", "gap analysis", "o que falta",
        "informacao em falta", "informacao ausente",
        "contradicoes", "inconsistencias",
        "nao coberto", "nao esta coberto",
        "por clarificar", "por investigar",
        "areas em falta", "pontos em falta",
        "o que nao sabemos",
    ),
)
