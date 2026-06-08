import { chartsApi } from '@/lib/api/charts'
import { multimodalApi } from '@/lib/api/multimodal'
import { isDataLikeFile } from '@/lib/utils/file-kind'
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
    parts.push(`<details>\n<summary>Pré-visualização dos dados</summary>\n\n${tablePreview}\n\n</details>`)
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
  if (!hasData && !(force && file)) {
    // No tabular file: only run when explicitly forced by the router AND there
    // is some inline data in the message (very long, comma/newline separated).
    if (!force || !isGraphRequest(message)) {
      return null
    }
  }
  if (!file && !(force && isGraphRequest(message))) {
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
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'graph_generator',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      file: fileMetadata(file),
      details: { error: error instanceof Error ? error.message : String(error) },
    })
    throw error
  }
}
