from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="report_builder",
    handler="text_instruction",
    description=(
        "Formatar e estruturar uma análise ou resposta existente em relatório formal, "
        "usando o contexto já disponível — sem pesquisar informação nova."
    ),
    routing_guidance=(
        "Usa quando o utilizador quer a resposta/análise formatada como relatório estruturado "
        "(com resumo executivo, secções, conclusões) a partir do contexto já disponível. "
        "Se o utilizador quer investigar ou pesquisar um tema novo, usa deep_research em vez deste."
    ),
    instruction=(
        "[Modo agente: Relatório]\n"
        "Produz uma estrutura de relatório real, compatível com índice: título, resumo executivo, "
        "introdução, metodologia/âmbito, secções H2/H3, análise, conclusões e recomendações. "
        "Usa headings Markdown."
    ),
    fallback_keywords=(
        "relatorio estruturado",
        "relatorio formal",
        "formato de relatorio",
        "estrutura de relatorio",
        "formata como relatorio",
        "apresenta como relatorio",
        "escreve em formato de relatorio",
    ),
)
