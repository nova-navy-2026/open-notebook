from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="sitrep",
    handler="text_instruction",
    description="Gerar um SITREP (Situation Report) no formato NATO/militar com base nos documentos disponíveis.",
    routing_guidance=(
        "Usa quando o utilizador pede um SITREP, relatório de situação, situation report, "
        "relatório de prontidão ou atualização de situação operacional."
    ),
    instruction=(
        "[Modo agente: SITREP]\n"
        "Gera um Situation Report (SITREP) em formato NATO/militar. Estrutura obrigatória:\n\n"
        "**DTG:** [Data-Hora-Grupo no formato DDHHMMZMMMYY]\n"
        "**FROM:** [Unidade/entidade emissora]\n"
        "**TO:** [Destinatário]\n"
        "**SUBJECT:** [Assunto resumido em maiúsculas]\n\n"
        "**1. SITUAÇÃO**\n"
        "Descrição concisa da situação atual. Contexto, âmbito e relevância operacional.\n\n"
        "**2. FORÇAS PRÓPRIAS (BLUE)**\n"
        "Estado, posição e atividade das forças/meios próprios relevantes.\n\n"
        "**3. FORÇAS ADVERSÁRIAS / AMEAÇAS (RED)**\n"
        "Informação conhecida sobre ameaças, adversários ou riscos. 'Nenhuma informação disponível' se não aplicável.\n\n"
        "**4. EVENTOS RELEVANTES**\n"
        "Lista numerada de eventos, incidentes ou ocorrências significativas no período.\n\n"
        "**5. AVALIAÇÃO**\n"
        "Análise e interpretação da situação. Implicações operacionais.\n\n"
        "**6. PRÓXIMAS AÇÕES**\n"
        "Ações planeadas ou recomendadas, com responsáveis e prazos se identificáveis.\n\n"
        "**7. PRÓXIMO RELATÓRIO**\n"
        "[Data/hora estimada do próximo SITREP ou 'A definir']\n\n"
        "Preenche com base nos documentos disponíveis. Indica 'Sem informação' quando dados insuficientes. "
        "Usa linguagem concisa e objetiva. Usa pt-PT."
    ),
    fallback_keywords=(
        "sitrep", "situation report", "relatorio de situacao",
        "sit rep", "relatorio operacional",
        "relatorio de prontidao", "atualizacao de situacao",
        "estado da situacao", "quadro de situacao",
        "relatorio de estado",
    ),
)
