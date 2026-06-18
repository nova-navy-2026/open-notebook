from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="glossary",
    handler="text_instruction",
    description="Criar glossário, lista de termos, siglas ou acrónimos a partir dos documentos.",
    routing_guidance=(
        "Usa quando o utilizador pede um glossário, lista de termos técnicos, definições, "
        "siglas, acrónimos ou léxico a partir dos documentos disponíveis."
    ),
    instruction=(
        "[Modo agente: Glossário]\n"
        "Extrai e define todos os termos técnicos, siglas e acrónimos relevantes. "
        "Para cada entrada indica: termo/sigla, definição clara e concisa, "
        "contexto de uso (se pertinente) e fonte/secção do documento. "
        "Ordena alfabeticamente. Usa pt-PT."
    ),
    fallback_keywords=(
        "glossario", "glossary", "termos", "termos tecnicos",
        "siglas", "acronimos", "definicoes",
        "lista de termos", "lista de siglas",
        "o que significa", "o que e",
        "lexico", "vocabulario tecnico",
        "dicionario",
    ),
)
