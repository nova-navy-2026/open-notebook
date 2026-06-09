from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="table_extraction",
    handler="text_instruction",
    description="Estruturar dados tabulares de texto/contexto em tabela.",
    routing_guidance=(
        "Usa para extrair ou estruturar tabelas a partir de texto/contexto/notas. "
        "Se houver ficheiro tabular e pedido de perfil/análise de dados, usa data_profiler; "
        "se houver pedido de gráfico, usa graph_generator."
    ),
    instruction=(
        "[Modo agente: Extração de tabelas]\n"
        "Se houver dados tabulares no contexto, extrai-os para Markdown. "
        "Preserva cabeçalhos, unidades, valores e notas. Se o utilizador pedir CSV, "
        "devolve também CSV num bloco de código. Não inventes células em falta."
    ),
    fallback_keywords=("tabela", "table", "csv", "excel", "colunas", "columns"),
)
