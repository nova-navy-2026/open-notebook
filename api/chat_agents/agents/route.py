from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="route",
    handler="route",
    description="Calcular rota, distância, tempo de viagem ou caminho entre dois locais.",
    routing_guidance="Usa quando existirem origem e destino ou pedido explícito de rota/distância/tempo/caminho.",
    parameters={
        "from": "origem da rota",
        "to": "destino da rota",
    },
    fallback_keywords=("rota", "route", "caminho", "trajeto", "itinerário", "itinerario", "distância", "distancia"),
)

