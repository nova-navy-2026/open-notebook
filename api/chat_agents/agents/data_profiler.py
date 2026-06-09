from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="data_profiler",
    handler="data_profiler",
    description=(
        "Analisar um ficheiro tabular e resumir colunas, tipos, valores em falta, "
        "intervalos, categorias e gráficos recomendados."
    ),
    routing_guidance=(
        "Usa quando o utilizador envia um ficheiro tabular (incluindo TXT delimitado) e pede para analisar, "
        "descrever, perfilar, validar, resumir ou perceber os dados antes de criar gráficos."
    ),
    parameters={
        "focus": "aspeto a analisar se indicado: qualidade, colunas, missing values, outliers, gráficos sugeridos",
    },
    fallback_keywords=(
        "perfil", "profile", "analisar dados", "analisa os dados", "data quality",
        "qualidade dos dados", "missing", "valores em falta", "outliers",
        "colunas", "columns", "describe data", "resumo dos dados", "dataset",
    ),
    file_type_prefixes=(
        "text/csv",
        "text/tab-separated-values",
        "text/plain",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/json",
        "application/jsonl",
        "application/x-ndjson",
    ),
)
