from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="timeline",
    handler="text_instruction",
    description="Criar cronologia ou linha temporal.",
    routing_guidance="Usa quando o pedido é organizar eventos por data/hora, ordem cronológica, história dos acontecimentos ou sequência temporal.",
    instruction=(
        "[Modo agente: Timeline]\n"
        "Constrói uma cronologia em ordem temporal. Para cada evento inclui data/hora se existir, "
        "evento, atores/entidades e fonte/evidência curta. Indica incertezas."
    ),
    fallback_keywords=(
        "timeline", "cronologia", "linha do tempo",
        "ordem cronologica", "sequencia temporal",
        "cronograma", "historia dos eventos", "historia dos acontecimentos",
        "quando aconteceu", "ordem dos acontecimentos",
        "evolucao cronologica",
    ),
)

