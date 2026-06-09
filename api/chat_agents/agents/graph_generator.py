from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="graph_generator",
    handler="graph_generator",
    description=(
        "Gerar gráficos (barras, linhas, dispersão, circular, histograma) a partir "
        "de um ficheiro CSV/Excel/JSON ou de dados tabulares enviados no chat."
    ),
    routing_guidance=(
        "Usa quando o utilizador envia um ficheiro tabular (CSV, TSV, TXT, Excel, JSON, "
        "JSONL/NDJSON) e pede para visualizar/plotar/desenhar um gráfico. Não uses "
        "para extrair uma tabela textual; nesse caso usa table_extraction."
    ),
    parameters={
        "chart_type": "tipo de gráfico pedido (barras, linhas, dispersão, circular, histograma)",
    },
    fallback_keywords=(
        "grafico", "gráfico", "graficos", "gráficos", "graph", "chart", "plot",
        "plotar", "visualizar", "visualizacao", "visualização", "diagrama",
        "barras", "linhas", "dispersao", "dispersão", "histograma", "scatter",
        "pie", "pizza", "csv", "tsv", "excel", "jsonl", "ndjson",
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
