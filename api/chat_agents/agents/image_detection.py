from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="image_detection",
    handler="multimodal",
    description="Detetar, contar, localizar ou segmentar objetos numa imagem.",
    routing_guidance="Usa para pedidos visuais como detetar, contar, identificar, localizar ou segmentar objetos em imagens.",
    parameters={
        "target": "objeto ou classe visual a detetar",
        "force_engine": "sam3 ou rfdetr se pedido explicitamente",
    },
    fallback_keywords=(
        "detetar", "detectar", "detect", "contar", "count", "segment",
        "identificar", "identify",
        # Engine-specific requests — "usa o sam3" / "usa o rfdetr" / "utiliza sam3"
        "sam3", "sam-3", "sam 3", "rfdetr", "rf-detr", "rf detr",
        "usa o sam", "utiliza o sam", "usa o rf", "utiliza o rf",
    ),
    file_type_prefixes=("image/",),
)

