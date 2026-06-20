export interface PageInfoContent {
  title: string
  description: string
  items: string[]
}

export type PageInfoKey =
  | 'chat'
  | 'sources'
  | 'search'
  | 'notebooks'
  | 'research'
  | 'visionImage'
  | 'visionVideo'
  | 'transcription'

type PageInfoMap = Record<PageInfoKey, PageInfoContent>

const ptPT: PageInfoMap = {
  chat: {
    title: 'O que pode fazer no Chat',
    description: 'Converse com todos os documentos a que tem acesso. O sistema direciona automaticamente cada mensagem para o agente mais adequado.',
    items: [
      '💬 Conversa geral — faça perguntas; o agente RAG responde com base nos documentos indexados.',
      '🔍 Deep Research — peça para investigar ou elaborar um relatório; o agente pesquisa autonomamente e apresenta o resultado no chat.',
      '📄 Resumo — peça "resume" ou "faz um resumo"; condensa documentos ou excertos nos pontos essenciais.',
      '📋 Pontos de ação — peça "pontos de ação" ou "next steps"; extrai tarefas, responsáveis e prazos.',
      '🏗️ Relatório estruturado — peça "relatório estruturado" para formatar o contexto com resumo executivo, secções e conclusões.',
      '⚔️ SITREP — peça "SITREP" ou "relatório de situação"; gera um Situation Report em formato NATO/militar.',
      '🕳️ Análise de lacunas — peça "lacunas" ou "o que falta"; identifica informação ausente e contradições.',
      '📖 Glossário — peça "glossário" ou "lista de siglas"; extrai e define termos técnicos e acrónimos.',
      '📅 Cronologia — peça "cronologia" ou "timeline"; organiza eventos por ordem temporal com datas e fontes.',
      '📊 Comparação documental — peça "compara" ou "diferenças"; confronta documentos, versões ou excertos.',
      '🔎 Extração de entidades — peça "lista de entidades" ou "quais os navios"; extrai pessoas, locais, navios e datas.',
      '✅ Checklist/Procedimento — peça "checklist" ou "procedimento"; gera passos operacionais numerados.',
      '🗺️ Rota — peça "rota de X para Y"; calcula trajetos, distâncias e tempos de viagem entre portos ou locais.',
      '🖼️ Análise visual — anexe imagens ou vídeo e escolha modo: Auto, Descrever, OCR, Detetar ou Seguir.',
      '🎙️ Transcrição — anexe áudio ou vídeo para transcrição automática com identificação de falantes.',
      '📈 Dados tabulares — anexe CSV, Excel, JSON ou NDJSON para perfilar dados ou gerar gráficos inline.',
      '🔬 Auditoria de fontes — peça "audita as fontes"; sinaliza claims sem suporte e contradições.',
      '🎤 Voz — clique no microfone para gravar; a mensagem é transcrita e enviada automaticamente.',
      '💾 Guardar nota — guarde respostas ou relatórios como nota num notebook com "Save to note".',
      '📥 Exportar — exporte a conversa em Markdown com o ícone de download no cabeçalho do chat.',
    ],
  },
  sources: {
    title: 'O que pode fazer nas Fontes',
    description: 'Faça a gestão de todos os documentos e materiais carregados.',
    items: [
      'Carregue ficheiros, URLs ou texto como novas fontes (a partir de um notebook).',
      'Pesquise fontes por título ou URL com a barra de pesquisa.',
      'Filtre por tipo (Link / Ficheiro / Texto) e por estado (Pronto / A processar / Não incorporado).',
      'Alterne entre vista em lista (tabela) e vista em grelha (cartões) com o botão no canto superior direito.',
      'Ordene pela data de criação clicando no cabeçalho "Criado".',
      'Abra uma fonte para conversar diretamente com ela ou para ver e gerir os seus insights.',
      'Apague uma fonte — remove o ficheiro, os embeddings e todos os insights.',
    ],
  },
  search: {
    title: 'O que pode fazer na Pesquisa',
    description: 'Encontre informação na sua base de conhecimento com controlo total sobre o modo de pesquisa.',
    items: [
      'Escolha o modo: Texto (correspondência exata de palavras-chave), Vetorial (semântica) ou Híbrido (combina os dois).',
      'Vetorial e Híbrido requerem um modelo de embedding configurado; Texto funciona sempre.',
      'Ative "Agrupar por tipo" para ver resultados organizados por Fontes, Notas, Insights e Documentos.',
      'As pesquisas recentes aparecem como chips clicáveis — reutilize-as com um clique.',
      'Expanda cada resultado para ver os fragmentos correspondentes e clique no título para abrir o objeto.',
      'Os resultados respeitam sempre as suas permissões e nível de acesso (classificação de segurança).',
    ],
  },
  notebooks: {
    title: 'O que pode fazer nos Notebooks',
    description: 'Organize a investigação em cadernos de trabalho com contexto selecionável.',
    items: [
      'Crie notebooks para agrupar fontes, notas e conversas sobre um tema.',
      'Selecione o contexto de cada fonte: off / apenas insights / conteúdo completo.',
      'Converse com o notebook — o chat usa exatamente o contexto selecionado.',
      'Use o profiler de dados ou o agente de gráficos no chat do notebook anexando dados tabulares.',
      'Audite a qualidade de fontes/evidência das respostas e relatórios do notebook.',
      'Use o agente de acompanhamento de procedimentos para ser guiado passo a passo.',
      'Adicione documentos da Marinha ao contexto consoante as suas permissões (até 15 documentos).',
      'Gere notas de investigação com o botão Research ou escreva notas manuais.',
    ],
  },
  research: {
    title: 'O que pode fazer na Deep Research',
    description: 'Conduza investigações aprofundadas com múltiplos agentes autónomos.',
    items: [
      'Lance investigações detalhadas sobre qualquer tema.',
      'Escolha o tipo de relatório (Research Report, Detailed Report, Deep Report, etc.) e o tom.',
      'Acompanhe o progresso em tempo real e consulte o relatório final renderizado.',
      'Quando a Deep Research é iniciada no chat, o progresso e o relatório aparecem no chat e também ficam guardados aqui.',
      'Use follow-ups no chat para criar revisões, resumos executivos ou alterações ao relatório.',
      'Guarde os resultados como notas num notebook para reutilização.',
      'O histórico de investigações é persistido — pode rever relatórios antigos a qualquer momento.',
    ],
  },
  visionImage: {
    title: 'O que pode fazer na Análise de Imagem',
    description: 'Detete, localize e segmente objetos em imagens com modelos de visão.',
    items: [
      'Carregue uma imagem (PNG, JPG, WEBP) por drag-and-drop ou clique.',
      'Escreva o que procura (ex: "barcos no cais", "coletes salva-vidas").',
      'Escolha o motor: SAM3 (vocabulário aberto) ou RF-DETR (classes COCO-91).',
      'Descarregue a imagem anotada com as caixas delimitadoras.',
      'Guarde o resultado como nota de imagem num notebook.',
    ],
  },
  visionVideo: {
    title: 'O que pode fazer no Seguimento de Vídeo',
    description: 'Acompanhe objetos ao longo de frames de vídeo.',
    items: [
      'Carregue um vídeo (MP4, MOV, AVI, …) por drag-and-drop.',
      'Defina o alvo a seguir em texto livre.',
      'Escolha o motor: SAM3 (vocabulário aberto) ou RF-DETR.',
      'Reveja o vídeo anotado com rastreamento interpolado entre frames.',
      'Descarregue o vídeo processado ou guarde-o como nota de vídeo.',
    ],
  },
  transcription: {
    title: 'O que pode fazer na Transcrição',
    description: 'Converta áudio e vídeo em texto com identificação automática de falantes.',
    items: [
      'Carregue um ficheiro de áudio ou vídeo (WAV, MP3, MP4, …).',
      'Especifique o idioma (ex: pt, en) ou deixe em branco para deteção automática.',
      'Ative a diarização para separar os falantes com cores e marcas de tempo.',
      'Copie o texto transcrito ou descarregue em TXT/SRT/VTT.',
      'Use a transcrição como base para notas ou fontes no notebook.',
    ],
  },
}

const enUS: PageInfoMap = {
  chat: {
    title: 'What you can do in Chat',
    description: 'Chat with every document you have access to. The system automatically routes each message to the most appropriate agent.',
    items: [
      '💬 General chat — ask questions; the RAG agent answers using your indexed documents.',
      '🔍 Deep Research — ask to investigate or write a detailed report; the agent researches autonomously and presents the result in chat.',
      '📄 Summarization — say "summarise" or "give me a summary"; condenses documents or excerpts into key points.',
      '📋 Action items — say "action items" or "next steps"; extracts tasks, owners and deadlines.',
      '🏗️ Structured report — say "structured report" to format existing context with executive summary, sections and conclusions.',
      '⚔️ SITREP — say "SITREP" or "situation report"; generates a NATO/military Situation Report.',
      '🕳️ Gap analysis — say "gaps" or "what is missing"; identifies absent information and contradictions.',
      '📖 Glossary — say "glossary" or "list of acronyms"; extracts and defines technical terms and abbreviations.',
      '📅 Timeline — say "timeline" or "chronology"; organises events in temporal order with dates and sources.',
      '📊 Document comparison — say "compare" or "differences"; contrasts documents, versions or excerpts.',
      '🔎 Entity extraction — say "list entities" or "which ships"; extracts people, places, vessels and dates.',
      '✅ Checklist / Procedure — say "checklist" or "procedure"; generates numbered operational steps.',
      '🗺️ Route — say "route from X to Y"; calculates routes, distances and travel times between ports or locations.',
      '🖼️ Visual analysis — attach images or video and choose a mode: Auto, Describe, OCR, Detect or Track.',
      '🎙️ Transcription — attach audio or video for automatic transcription with speaker identification.',
      '📈 Tabular data — attach CSV, Excel, JSON or NDJSON to profile data or generate inline charts.',
      '🔬 Source audit — say "audit sources"; flags unsupported claims and contradictions.',
      '🎤 Voice input — click the microphone to record; the message is transcribed and sent automatically.',
      '💾 Save note — save answers or reports as a notebook note with "Save to note".',
      '📥 Export — export the conversation to Markdown with the download icon in the chat header.',
    ],
  },
  sources: {
    title: 'What you can do in Sources',
    description: 'Manage all your uploaded documents and materials.',
    items: [
      'Upload files, URLs or text as new sources (from inside a notebook).',
      'Search sources by title or URL using the search bar.',
      'Filter by type (Link / File / Text) and by status (Ready / Processing / Not embedded).',
      'Switch between list view (table) and grid view (cards) with the button in the top-right.',
      'Sort by creation date by clicking the "Created" column header.',
      'Open a source to chat directly with it or to view and manage its insights.',
      'Delete a source — removes the file, embeddings and all insights.',
    ],
  },
  search: {
    title: 'What you can do in Search',
    description: 'Find information across your knowledge base with full control over the search mode.',
    items: [
      'Choose a mode: Text (exact keyword match), Vector (semantic) or Hybrid (combines both).',
      'Vector and Hybrid require a configured embedding model; Text always works.',
      'Enable "Group by type" to see results organised by Sources, Notes, Insights and Documents.',
      'Recent searches appear as clickable chips — reuse them in one click.',
      'Expand each result to see matching fragments and click the title to open the object.',
      'Results always respect your permissions and access level (security classification).',
    ],
  },
  notebooks: {
    title: 'What you can do in Notebooks',
    description: 'Organise research into working notebooks with selectable context.',
    items: [
      'Create notebooks to group sources, notes and conversations around a topic.',
      'Set each source context: off / insights only / full content.',
      'Chat with the notebook — the chat uses exactly the context you selected.',
      'Use the data profiler or graph agent in notebook chat by attaching tabular data.',
      'Audit source/evidence quality for notebook answers and reports.',
      'Use the procedure-following agent to be guided step by step through any procedure.',
      'Add Navy documents to the context based on your permissions (up to 15 documents).',
      'Generate research notes with the Research button or write manual notes.',
    ],
  },
  research: {
    title: 'What you can do in Deep Research',
    description: 'Run in-depth investigations with multiple autonomous agents.',
    items: [
      'Launch detailed investigations on any topic.',
      'Choose the report type (Research Report, Detailed Report, Deep Report, etc.) and tone.',
      'Track progress in real time and read the rendered final report.',
      'When Deep Research starts from chat, progress and the final report appear in chat and are also saved here.',
      'Use chat follow-ups to create revisions, executive summaries or changes to the report.',
      'Save results as notes in a notebook for reuse.',
      'The job history is persisted — review past reports at any time.',
    ],
  },
  visionImage: {
    title: 'What you can do in Image Analysis',
    description: 'Detect, locate and segment objects in images with vision models.',
    items: [
      'Upload an image (PNG, JPG, WEBP) by drag-and-drop or click.',
      'Describe what you are looking for (e.g. "boats at the dock", "life vests").',
      'Choose the engine: SAM3 (open vocabulary) or RF-DETR (COCO-91 classes).',
      'Download the annotated image with bounding boxes.',
      'Save the result as an image note in a notebook.',
    ],
  },
  visionVideo: {
    title: 'What you can do in Video Tracking',
    description: 'Track objects across video frames.',
    items: [
      'Upload a video (MP4, MOV, AVI, …) by drag-and-drop.',
      'Define the target to track in free text.',
      'Choose the engine: SAM3 (open vocabulary) or RF-DETR.',
      'Review the annotated video with interpolated tracking between frames.',
      'Download the processed video or save it as a video note.',
    ],
  },
  transcription: {
    title: 'What you can do in Transcription',
    description: 'Convert audio and video into text with automatic speaker identification.',
    items: [
      'Upload an audio or video file (WAV, MP3, MP4, …).',
      'Specify the language (e.g. pt, en) or leave blank for auto-detection.',
      'Enable diarization to separate speakers with colours and timestamps.',
      'Copy the transcript or download in TXT/SRT/VTT.',
      'Use the transcription as a basis for notes or sources in a notebook.',
    ],
  },
}

const MAP_BY_LANGUAGE: Record<string, PageInfoMap> = {
  'pt-PT': ptPT,
  'pt-BR': ptPT,
  'en-US': enUS,
}

export function getPageInfoContent(pageKey: PageInfoKey, language?: string): PageInfoContent {
  const lang = language ?? 'pt-PT'
  const map = MAP_BY_LANGUAGE[lang] ?? (lang.startsWith('pt') ? ptPT : enUS)
  return map[pageKey]
}
