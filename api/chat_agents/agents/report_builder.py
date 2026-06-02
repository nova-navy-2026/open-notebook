from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="report_builder",
    handler="text_instruction",
    description="Redigir resposta em estrutura de relatório sem iniciar pesquisa profunda.",
    routing_guidance="Usa para relatório normal/estruturado quando o utilizador não pediu deep research.",
    instruction=(
        "[Modo agente: Relatório]\n"
        "Produz uma estrutura de relatório real, compatível com índice: título, resumo executivo, "
        "introdução, metodologia/âmbito, secções H2/H3, análise, conclusões e recomendações. "
        "Usa headings Markdown."
    ),
    fallback_keywords=("relatório", "relatorio", "report"),
)
