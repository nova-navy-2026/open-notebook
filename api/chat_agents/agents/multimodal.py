from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="multimodal",
    handler="multimodal",
    description="Pergunta geral sobre uma imagem ou vídeo.",
    routing_guidance="Usa para descrever, explicar ou responder sobre conteúdo visual sem pedido explícito de OCR/deteção.",
    file_type_prefixes=("image/", "video/"),
)

