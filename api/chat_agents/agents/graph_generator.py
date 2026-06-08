from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="graph_generator",
    handler="graph_generator",
    description=(
        "Gerar gráficos (barras, linhas, dispersão, circular, histograma) a partir "
        "de um ficheiro CSV/Excel/JSON ou de dados tabulares enviados no chat."
    ),
    routing_guidance=(
        "Usa quando o utilizador envia dados tabulares (CSV, Excel, JSON) ou pede "
        "para visualizar/plotar/desenhar um gráfico, chart, diagrama ou tabela de dados."
    ),
    parameters={
        "chart_type": "tipo de gráfico pedido (barras, linhas, dispersão, circular, histograma)",
    },
    fallback_keywords=(
        "grafico", "gráfico", "graficos", "gráficos", "graph", "chart", "plot",
        "plotar", "visualizar", "visualizacao", "visualização", "diagrama",
        "barras", "linhas", "dispersao", "dispersão", "histograma", "scatter",
        "pie", "pizza", "csv", "excel",
    ),
    file_type_prefixes=(
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/json",
    ),
)
