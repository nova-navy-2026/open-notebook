from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="translation",
    handler="text_instruction",
    description="Traduzir texto ou documentos de um idioma para outro.",
    routing_guidance=(
        "Usa quando o utilizador pede para traduzir conteúdo, documentos ou texto "
        "para outro idioma. Extrai o idioma alvo da mensagem do utilizador."
    ),
    instruction=(
        "[Modo agente: Tradução]\n"
        "Traduz o texto ou o conteúdo relevante dos documentos para o idioma indicado pelo utilizador. "
        "Se o utilizador não especificar o idioma alvo, traduz para inglês. "
        "Preserva a estrutura, formatação e terminologia técnica original. "
        "Não omitas informação — traduz o conteúdo completo pedido. "
        "Não adiciones comentários ou explicações fora do texto traduzido."
    ),
    fallback_keywords=(
        "traduz", "traduzir", "translate", "translation", "traducao", "tradução",
        "traduzido", "em ingles", "em inglês", "em portugues", "em português",
        "em frances", "em francês", "para ingles", "para inglês",
        "para portugues", "para português", "para frances", "para francês",
        "in english", "in portuguese", "in french",
    ),
)
