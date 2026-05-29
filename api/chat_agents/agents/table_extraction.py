from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="table_extraction",
    handler="text_instruction",
    description="Estruturar dados tabulares de texto/contexto em tabela.",
    routing_guidance="Usa para pedidos de tabela, CSV, Excel, colunas ou extração tabular sem ficheiro visual.",
    instruction=(
        "[Modo agente: Extração de tabelas]\n"
        "Se houver dados tabulares no contexto, extrai-os para Markdown. "
        "Preserva cabeçalhos, unidades, valores e notas. Se o utilizador pedir CSV, "
        "devolve também CSV num bloco de código. Não inventes células em falta."
    ),
    fallback_keywords=("tabela", "table", "csv", "excel", "colunas", "columns"),
)

