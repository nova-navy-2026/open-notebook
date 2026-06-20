from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="document_comparison",
    handler="text_instruction",
    description="Comparar documentos, versões ou excertos.",
    routing_guidance="Usa para pedidos de comparação, diferenças, semelhanças, alterações, evolução entre versões, ou confronto de documentos/excertos.",
    instruction=(
        "[Modo agente: Comparação documental]\n"
        "Compara os documentos, notas ou excertos relevantes. Estrutura por semelhanças, "
        "diferenças, alterações críticas, impacto prático e pontos que exigem validação."
    ),
    fallback_keywords=(
        "compara", "comparar", "compare", "comparison",
        "diferencas", "versus",
        "contrasta", "contrastar",
        "semelhancas", "similares",
        "confronta", "confrontar",
        "alteracoes entre", "evolucao entre", "versao anterior",
        "qual a diferenca", "em que diferem",
    ),
)

