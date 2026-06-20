from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="deep_research",
    handler="deep_research",
    description=(
        "Fazer uma pesquisa aprofundada, investigação ou redigir um relatório detalhado "
        "sobre um tema — com acesso a fontes externas além dos documentos disponíveis."
    ),
    routing_guidance=(
        "Usa quando o utilizador pede para: 'fazer um relatório', 'fazer uma pesquisa', "
        "'investigar', 'analisar em profundidade', 'elaborar um relatório', "
        "'escrever um relatório' ou variantes semânticas equivalentes; "
        "ou quando deep_research_enabled=true. "
        "Prefere normal_chat apenas se o utilizador pede explicitamente para responder "
        "com base nos documentos/contexto já disponíveis."
    ),
    parameters={
        "report_type": "tipo de relatório se indicado",
        "tone": "estilo de escrita se indicado",
    },
    fallback_keywords=(
        "deep research",
        "pesquisa profunda",
        "relatorio profundo",
        "relatorio aprofundado",
        "pesquisa aprofundada",
        "investigacao profunda",
        "investigacao aprofundada",
        "analise aprofundada",
        "faz um relatorio",
        "faz uma pesquisa",
        "elabora um relatorio",
        "cria um relatorio",
        "escreve um relatorio",
        "prepara um relatorio",
        "redige um relatorio",
    ),
)

