from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="save_note",
    handler="save_note",
    description="Guardar a resposta anterior como nota.",
    routing_guidance="Usa quando o utilizador pede para guardar, salvar, criar ou adicionar uma nota/notebook.",
    parameters={"notebook": "nome/id do notebook alvo se indicado"},
    fallback_keywords=(
        "guardar nota",
        "guarda isto como nota",
        "guarda como nota",
        "guardar isto como nota",
        "guardar como nota",
        "salva isto como nota",
        "salvar nota",
        "salva como nota",
        "salvar isto como nota",
        "salvar como nota",
        "save note",
        "save this as note",
        "save as note",
        "create note",
        "criar nota",
        "adicionar nota",
    ),
)
