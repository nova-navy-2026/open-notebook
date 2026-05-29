from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="save_note",
    handler="save_note",
    description="Guardar a resposta anterior como nota.",
    routing_guidance="Usa quando o utilizador pede para guardar, salvar, criar ou adicionar uma nota/notebook.",
    parameters={"notebook": "nome/id do notebook alvo se indicado"},
    fallback_keywords=("guarda", "guardar", "salva", "salvar", "save", "nota", "note", "notebook"),
)

