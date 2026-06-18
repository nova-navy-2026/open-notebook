from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="summarization",
    handler="text_instruction",
    description="Resumir, sintetizar ou condensar documentos, excertos ou conversas.",
    routing_guidance=(
        "Usa quando o utilizador pede para resumir, sintetizar, condensar ou fazer um sumário "
        "de documentos, notas, excertos ou da conversa. "
        "Não usar para análise comparativa (document_comparison) nem para investigação nova (deep_research)."
    ),
    instruction=(
        "[Modo agente: Resumo]\n"
        "Produz um resumo estruturado e conciso. Inclui: pontos-chave, factos essenciais, "
        "decisões ou conclusões principais, e o que foi omitido. "
        "Adapta a extensão à complexidade do material. Usa pt-PT."
    ),
    fallback_keywords=(
        "resume", "resumo", "resumir", "sintetiza", "sintese", "sintetizar",
        "sumario", "faz um resumo", "faz uma sintese",
        "condensa", "condensar", "em resumo",
        "principais pontos", "pontos principais",
        "resumo executivo", "executive summary",
        "tl;dr", "tldr",
    ),
)
