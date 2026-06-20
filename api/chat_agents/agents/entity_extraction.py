from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="entity_extraction",
    handler="text_instruction",
    description="Extrair entidades como pessoas, organizações, locais, datas, navios, códigos ou coordenadas.",
    routing_guidance="Usa quando o pedido principal é listar, organizar ou extrair entidades como pessoas, navios, locais, datas ou identificadores do contexto disponível.",
    instruction=(
        "[Modo agente: Extração de entidades]\n"
        "Extrai entidades relevantes e organiza por tipo: pessoas, organizações, locais, "
        "navios/meios, datas, documentos, códigos, coordenadas e outros identificadores. "
        "Inclui evidência curta quando possível."
    ),
    fallback_keywords=(
        "entidades", "entities",
        "extrai entidades", "lista de entidades", "identifica entidades",
        "lista de pessoas", "quais as pessoas", "que pessoas",
        "lista de navios", "quais os navios", "que navios",
        "lista de locais", "quais os locais",
        "lista de organizacoes", "quais as organizacoes",
        "lista de datas", "datas mencionadas",
        "coordenadas", "identificadores",
    ),
)

