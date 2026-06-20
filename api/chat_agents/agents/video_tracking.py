from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="video_tracking",
    handler="multimodal",
    description="Detetar, contar, localizar ou seguir objetos num vídeo.",
    routing_guidance="Usa para pedidos de deteção, contagem, localização ou seguimento de alvos em vídeo.",
    parameters={
        "target": "objeto ou classe visual a detetar/seguir",
        "force_engine": "sam3 ou rfdetr se pedido explicitamente",
    },
    fallback_keywords=(
        "detetar", "detectar", "detect", "contar", "count", "seguir", "track", "rastrear",
        # Engine-specific requests
        "sam3", "sam-3", "sam 3", "rfdetr", "rf-detr", "rf detr",
        "usa o sam", "utiliza o sam", "usa o rf", "utiliza o rf",
    ),
    file_type_prefixes=("video/",),
)

