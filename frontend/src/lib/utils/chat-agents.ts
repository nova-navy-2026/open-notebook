import type { NotebookChatMessage } from '@/lib/types/api'
import type { NavigationRouteResponse } from '@/lib/api/navigation'
import type { TranscriptionResult } from '@/lib/api/transcription'
import { isAudioLikeFile } from '@/lib/utils/file-kind'

export interface ChatDeepResearchOptions {
  reportType: string
  tone: string
  modelId?: string
  modelName?: string
}

export interface ChatAgentUiOptions {
  transcription?: {
    language?: string
    diarize?: boolean
    numSpeakers?: number
  }
  vision?: {
    engine?: 'auto' | 'sam3' | 'rfdetr'
    mode?: 'auto' | 'describe' | 'ocr' | 'detect' | 'track'
  }
  saveNote?: {
    notebookId?: string
  }
}

export function normaliseForAgentMatching(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

export function isAudioFile(file?: File | null): file is File {
  return isAudioLikeFile(file)
}

export function isTranscriptionRequest(message: string, file?: File | null): boolean {
  const text = normaliseForAgentMatching(message)
  return (
    isAudioFile(file)
    || /\b(transcrever|transcricao|transcription|transcribe|whisper|audio|fala|speech|diarizar|diarization|speaker|orador)\b/.test(text)
  )
}

export function wantsDiarization(message: string): boolean {
  const text = normaliseForAgentMatching(message)
  return /\b(diarizar|diarizacao|diarization|speaker|speakers|orador|oradores|falante|falantes|quem fala|quem falou|identificar falantes)\b/.test(text)
}

export function parseRouteRequest(message: string): { from: string; to: string } | null {
  const trimmed = message.trim()
  const patterns = [
    /\b(?:rota|route|caminho|trajeto|itinerario|itinerário|itinerary)\s+(?:de|from)\s+(.+?)\s+(?:para|to|ate|até)\s+(.+?)(?:[?.!]|$)/i,
    /\b(?:distancia|distância|distance|tempo|duration)\s+(?:de|from)\s+(.+?)\s+(?:para|to|ate|até)\s+(.+?)(?:[?.!]|$)/i,
    /\b(?:como|how)\s+(?:ir|chegar|go|get)\s+(?:de|from)\s+(.+?)\s+(?:para|to|ate|até)\s+(.+?)(?:[?.!]|$)/i,
  ]
  for (const pattern of patterns) {
    const match = trimmed.match(pattern)
    if (match?.[1] && match?.[2]) {
      return { from: match[1].trim(), to: match[2].trim() }
    }
  }
  return null
}

export function formatRouteResponse(result: NavigationRouteResponse, from: string, to: string): string {
  const distance = typeof result.distance_km === 'number'
    ? `${result.distance_km.toFixed(1)} km`
    : 'não disponível'
  const duration = typeof result.duration_min === 'number'
    ? `${Math.round(result.duration_min)} min`
    : typeof result.estimated_time === 'string' && result.estimated_time.trim()
      ? result.estimated_time.trim()
      : 'não disponível'
  const preference = result.route_preference ? `\n- Preferência: ${result.route_preference}` : ''
  const source = result.source ? `\n- Fonte: ${result.source}` : ''
  return [
    `Rota calculada de ${from} para ${to}:`,
    '',
    `- Distância: ${distance}`,
    `- Tempo estimado: ${duration}${preference}${source}`,
  ].join('\n')
}

function formatSegmentTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return '00:00'
  const totalSeconds = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(totalSeconds / 60)
  const remainder = totalSeconds % 60
  return `${minutes}:${remainder.toString().padStart(2, '0')}`
}

export function formatTranscriptionResponse(result: TranscriptionResult): string {
  const parts = ['Transcrição concluída.']
  if (result.language) parts.push(`Idioma: ${result.language}`)
  if (result.provider || result.model) {
    parts.push(`Motor: ${[result.provider, result.model].filter(Boolean).join(' / ')}`)
  }
  const transcript = result.dialog
    || result.segments?.map((segment) => {
      const speaker = segment.speaker ? `${segment.speaker}: ` : ''
      return `[${formatSegmentTime(segment.start)}-${formatSegmentTime(segment.end)}] ${speaker}${segment.text}`.trim()
    }).join('\n')
    || result.text
    || ''
  return `${parts.join('\n')}\n\n${transcript}`.trim()
}

export function instructionForVisualMode(mode?: ChatAgentUiOptions['vision'] extends infer V ? V extends { mode?: infer M } ? M : never : never): string | undefined {
  switch (mode) {
    case 'describe':
      return 'Modo visual selecionado: descreve e explica o conteúdo visual de forma estruturada.'
    case 'ocr':
      return 'Modo visual selecionado: faz OCR; extrai texto, tabelas, rótulos, placas e conteúdo escrito. Preserva estrutura quando possível.'
    case 'detect':
      return 'Modo visual selecionado: deteta, identifica, conta e localiza objetos/alvos visíveis. Indica incerteza.'
    case 'track':
      return 'Modo visual selecionado: acompanha/segue objetos ou alvos no vídeo, resumindo movimento, localização e eventos.'
    default:
      return undefined
  }
}

export function lastAssistantMessage(messages: NotebookChatMessage[]): NotebookChatMessage | undefined {
  return [...messages].reverse().find((message) => message.type === 'ai' && message.content.trim())
}

export function isSaveToNoteRequest(message: string): boolean {
  const text = normaliseForAgentMatching(message)
  return /\b(guarda|guardar|salva|salvar|save|cria|criar|create|adiciona|adicionar|add)\b.*\b(nota|note|notebook|caderno)\b/.test(text)
}

export function parseSaveToNoteTarget(message: string): string | undefined {
  const trimmed = message.trim()
  const patterns = [
    /\b(?:notebook|caderno)\s+["“”']?([^"“”'.!?]+)["“”']?/i,
    /\b(?:no|na|ao|a|para|to|in|into)\s+(?:notebook|caderno)\s+["“”']?([^"“”'.!?]+)["“”']?/i,
    /\b(?:no|na|ao|para|to|into)\s+["“”']?([^"“”'.!?]+)["“”']?\s+(?:notebook|caderno)\b/i,
  ]

  for (const pattern of patterns) {
    const match = trimmed.match(pattern)
    const target = match?.[1]?.trim()
    if (target) return target
  }

  return undefined
}

/**
 * Offline fallback only. The authoritative instruction for each text agent
 * lives in the backend agent definitions (`api/chat_agents/agents/*.py`) and is
 * delivered via the router response (`routerDecision.instruction`). This
 * client-side heuristic is used purely as a degraded mode when the router
 * endpoint is unreachable, so keep it broadly aligned but treat the backend as
 * the source of truth.
 */
export function detectTextAgentInstruction(message: string): string | undefined {
  const text = normaliseForAgentMatching(message)

  if (/\b(tabela|table|csv|excel|colunas|columns)\b/.test(text)) {
    return '[Modo agente: Extração de tabelas]\nSe houver dados tabulares no contexto, extrai-os para Markdown. Preserva cabeçalhos, unidades, valores e notas. Se o utilizador pedir CSV, devolve também CSV num bloco de código. Não inventes células em falta.'
  }

  if (/\b(compara|comparar|compare|comparison|diferencas|diferenças|versus| vs )\b/.test(text)) {
    return '[Modo agente: Comparação documental]\nCompara os documentos, notas ou excertos relevantes. Estrutura por semelhanças, diferenças, alterações críticas, impacto prático e pontos que exigem validação.'
  }

  if (/\b(checklist|procedimento|procedimentos|procedure|passos|steps|instrucoes|instruções)\b/.test(text)) {
    return '[Modo agente: Checklist/Procedimento]\nTransforma a resposta num procedimento operacional claro. Usa passos numerados, pré-condições, verificações, riscos/atenções e resultado esperado. Mantém pt-PT.'
  }

  if (/\b(guia-me|guia me|acompanha|acompanhar|passo a passo|step by step|guide me|tutorial|orienta-me|orienta me)\b/.test(text)) {
    return '[Modo agente: Acompanhamento de procedimento]\nGuia o utilizador de forma interativa. Usa a conversa recente para saber o último passo confirmado. Mostra apenas o próximo passo acionável, com como validar conclusão, e pergunta se pode avançar. Se ainda não houver procedimento definido, primeiro identifica objetivo, pré-condições e número de passos.'
  }

  if (/\b(entidades|entities|extrair entidades|entity extraction|pessoas|locais|organizacoes|organizações|datas|navios|ships)\b/.test(text)) {
    return '[Modo agente: Extração de entidades]\nExtrai entidades relevantes e organiza por tipo: pessoas, organizações, locais, navios/meios, datas, documentos, códigos, coordenadas e outros identificadores. Inclui evidência curta quando possível.'
  }

  if (/\b(timeline|cronologia|linha do tempo|ordem cronologica|ordem cronológica)\b/.test(text)) {
    return '[Modo agente: Timeline]\nConstrói uma cronologia em ordem temporal. Para cada evento inclui data/hora se existir, evento, atores/entidades e fonte/evidência curta. Indica incertezas.'
  }

  if (/\b(relatorio|relatório|report)\b/.test(text)) {
    return '[Modo agente: Relatório]\nProduz uma estrutura de relatório real, compatível com índice: título, resumo executivo, introdução, metodologia/âmbito, secções H2/H3, análise, conclusões e recomendações. Usa headings Markdown.'
  }

  if (/\b(auditar fontes|auditoria de fontes|verificar fontes|qualidade das fontes|source quality|citations|citacoes|citações|evidencia|evidência|sem suporte|unsupported|fiabilidade|confianca|confiança|validar|fact-check|fact check)\b/.test(text)) {
    return '[Modo agente: Auditoria de qualidade de fontes]\nAudita a resposta/relatório/contexto disponível. Organiza por: claims principais, evidência disponível, claims sem suporte, fontes fracas ou desatualizadas, contradições, lacunas de informação, nível de confiança e recomendações de validação. Não inventes fontes. Se falta evidência, diz explicitamente.'
  }

  return undefined
}

export function applyTextAgentInstruction(message: string): string {
  const base = message.trim()
  const instruction = detectTextAgentInstruction(message)
  return instruction ? `${base}\n\n${instruction}` : base
}
