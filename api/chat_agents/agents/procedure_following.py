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
        "Atuas como um guia interativo. Quando detetares um procedimento passo a passo, "
        "acompanha o utilizador do início ao fim:\n"
        "1. Apresenta primeiro uma visão geral curta e o número total de passos.\n"
        "2. Apresenta APENAS um passo de cada vez, de forma clara e acionável, com "
        "pré-condições, ação a executar e como confirmar que ficou concluído.\n"
        "3. No fim de cada passo, pergunta se o utilizador concluiu ou se precisa de ajuda, "
        "e só avança para o passo seguinte após confirmação.\n"
        "4. Se o utilizador relatar um problema, ajuda a resolver antes de continuar.\n"
        "5. Indica sempre o progresso (ex.: 'Passo 2 de 7'). Mantém pt-PT."
    ),
    fallback_keywords=(
        "guia-me", "guia me", "acompanha", "acompanhar", "passo a passo",
        "guia passo", "step by step", "guide me", "ensina-me", "ensina me",
        "como faço", "como faco", "tutorial", "orienta-me", "orienta me",
    ),
)
