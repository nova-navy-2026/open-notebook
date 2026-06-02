from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="ocr",
    handler="multimodal",
    description="Extrair ou ler texto, tabelas, placas, documentos, screenshots ou conteúdo escrito numa imagem/vídeo.",
    routing_guidance="Usa quando o utilizador quer ler texto, extrair tabela/CSV ou recuperar conteúdo escrito de media visual.",
    parameters={"target": "texto, tabela ou área textual a extrair se indicado"},
    fallback_keywords=("ocr", "texto", "text", "ler", "read", "extrair", "extract", "tabela", "table", "csv"),
    file_type_prefixes=("image/", "video/"),
)

