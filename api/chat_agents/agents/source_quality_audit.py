from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="source_quality_audit",
    handler="text_instruction",
    description=(
        "Auditar qualidade de fontes/evidência: claims sem suporte, citações fracas, "
        "lacunas, contradições e próximos passos de validação."
    ),
    routing_guidance=(
        "Usa quando o utilizador pede para verificar evidência, fontes, citações, "
        "fiabilidade, qualidade ou robustez de uma resposta, relatório, nota ou contexto."
    ),
    instruction=(
        "[Modo agente: Auditoria de qualidade de fontes]\n"
        "Audita a resposta/relatório/contexto disponível. Organiza por: claims principais, "
        "evidência disponível, claims sem suporte, fontes fracas ou desatualizadas, "
        "contradições, lacunas de informação, nível de confiança e recomendações de validação. "
        "Não inventes fontes. Se falta evidência, diz explicitamente."
    ),
    fallback_keywords=(
        "auditar fontes", "auditoria de fontes", "verificar fontes", "qualidade das fontes",
        "source quality", "citations", "citações", "citacoes", "evidência",
        "evidencia", "sem suporte", "unsupported", "fiabilidade", "confianca",
        "confiança", "validar", "fact-check", "fact check",
    ),
)
