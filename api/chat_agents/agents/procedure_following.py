from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="procedure_following",
    handler="text_instruction",
    description=(
        "Guiar o utilizador passo a passo ao longo de um procedimento, do início ao fim."
    ),
    routing_guidance=(
        "Usa quando o utilizador quer ser GUIADO interativamente por um procedimento, "
        "tutorial ou sequência de passos (não apenas listar os passos). Distingue de "
        "'checklist_procedure', que apenas resume os passos num documento."
    ),
    instruction=(
        "[Modo agente: Acompanhamento de procedimento]\n"
        "Atuas como um guia interativo com estado conversacional. Usa a conversa recente "
        "para perceber que passo já foi confirmado e nunca reinicies o procedimento sem "
        "necessidade. Mostra apenas o próximo passo acionável, com pré-condições, ação, "
        "validação de conclusão e pergunta se podes avançar. Se o utilizador relatar um "
        "problema, ajuda a resolver antes de continuar. Indica sempre progresso "
        "(ex.: 'Passo 2 de 7'). Mantém pt-PT."
    ),
    fallback_keywords=(
        "guia-me", "guia me", "acompanha", "acompanhar", "passo a passo",
        "guia passo", "step by step", "guide me", "ensina-me", "ensina me",
        "como faço", "como faco", "tutorial", "orienta-me", "orienta me",
    ),
)
