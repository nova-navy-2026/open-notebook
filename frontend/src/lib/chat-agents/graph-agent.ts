import { chartsApi } from '@/lib/api/charts'
import { multimodalApi } from '@/lib/api/multimodal'
import { isDataLikeFile } from '@/lib/utils/file-kind'
import { formatApiError } from '@/lib/utils/error-handler'
import {
  fileMetadata,
  logChatAgentEvent,
  previewMessage,
  type ChatAgentRunContext,
} from '@/lib/chat-agents/logger'

function normalise(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

function looksLikeInlineTable(message: string): boolean {
  const lines = message
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines.length < 2) return false

  const separators = [',', ';', '\t', '|']
  return separators.some((separator) => {
    const counts = lines.slice(0, 5).map((line) => line.split(separator).length)
    return counts[0] > 1 && counts.filter((count) => count === counts[0]).length >= 2
  })
}

function isHttpStatus(error: unknown, status: number): boolean {
  return (error as { response?: { status?: number } })?.response?.status === status
}

export function isGraphRequest(message: string): boolean {
  const text = normalise(message)
  return /\b(grafico|graficos|graph|chart|plot|plotar|visualizar|visualizacao|diagrama|barras|linhas|dispersao|histograma|scatter|pie|pizza|boxplot)\b/.test(text)
}

async function formatChartResponse(
  text: string,
  imageDataUrl?: string | null,
  tablePreview?: string | null,
): Promise<string> {
  const parts: string[] = [text]
  if (imageDataUrl) {
    const imageUrl = await multimodalApi.saveNoteAsset(imageDataUrl).catch(() => imageDataUrl)
    parts.push(`![Gráfico gerado](${imageUrl})`)
  }
  if (tablePreview) {
    parts.push(`### Pré-visualização dos dados\n\n${tablePreview}`)
  }
  return parts.filter((part) => part && part.trim()).join('\n\n')
}

/**
 * Graph generator agent: turns a tabular file (CSV/Excel/JSON) plus a
 * natural-language request into a rendered chart shown inline (and
 * downloadable). Returns null when it does not apply so the caller can fall
 * through to the next agent.
 */
export async function runGraphAgent(
  message: string,
  file?: File,
  context?: ChatAgentRunContext,
  force = false,
): Promise<string | null> {
  const hasData = isDataLikeFile(file)
  const hasInlineTable = !file && looksLikeInlineTable(message)
  if (file && !hasData) {
    return null
  }
  if (!hasData && !hasInlineTable) {
    return null
  }

  const startedAt = performance.now()
  logChatAgentEvent({
    surface: context?.surface ?? 'global_chat',
    agent: 'graph_generator',
    event: 'selected',
    status: 'selected',
    context,
    message_preview: previewMessage(message),
    file: fileMetadata(file),
    details: { forced: force },
  })

  try {
    const result = await chartsApi.generate({
      query: message,
      file,
      data: file ? undefined : message,
      surface: context?.surface,
      run_id: context?.runId,
      session_id: context?.sessionId,
      notebook_id: context?.notebookId,
      model_id: context?.modelId,
    })
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'graph_generator',
      event: 'tool_call',
      status: 'success',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      file: fileMetadata(file),
      details: {
        chart_type: (result.spec?.chart_type as string) ?? undefined,
        has_image_result: Boolean(result.image_base64),
      },
    })
    return formatChartResponse(result.text, result.image_base64, result.table_preview)
  } catch (error) {
    const errorMessage = formatApiError(error)
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'graph_generator',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      file: fileMetadata(file),
      details: { error: errorMessage },
    })
    if (isHttpStatus(error, 400) || isHttpStatus(error, 422)) {
      return [
        'Não consegui gerar o gráfico porque os dados enviados não parecem ser uma tabela válida.',
        `Detalhe: ${errorMessage}`,
        'Envia um ficheiro CSV, TSV, Excel ou JSON com colunas bem definidas, ou cola dados tabulares em formato CSV.',
      ].join('\n\n')
    }
    throw error
  }
}
