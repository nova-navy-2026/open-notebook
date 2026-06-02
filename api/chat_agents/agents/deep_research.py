from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="deep_research",
    handler="deep_research",
    description="Iniciar pesquisa profunda ou relatório profundo.",
    routing_guidance="Só usa se o utilizador pedir explicitamente pesquisa profunda ou se deep_research_enabled=true.",
    parameters={
        "report_type": "tipo de relatório se indicado",
        "tone": "estilo de escrita se indicado",
    },
    fallback_keywords=("deep research", "pesquisa profunda", "relatório profundo", "relatorio profundo"),
)

