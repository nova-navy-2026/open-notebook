import { chartsApi } from '@/lib/api/charts'
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

export function isDataProfileRequest(message: string): boolean {
  const text = normalise(message)
  const profileIntent = /\b(perfil|profile|analisa|analisar|analyze|describe|resumo|summary|data quality|qualidade|missing|valores em falta|outliers|colunas|columns)\b/.test(text)
  const chartIntent = /\b(grafico|graficos|graph|chart|plot|plotar|visualizar|visualizacao|barras|linhas|dispersao|histograma|scatter|pie|pizza)\b/.test(text)
  if (chartIntent && !profileIntent) return false
  return profileIntent || /\b(dataset|dados)\b/.test(text)
}

export async function runDataProfilerAgent(
  message: string,
  file?: File,
  context?: ChatAgentRunContext,
  force = false,
): Promise<string | null> {
  if (!file || !isDataLikeFile(file)) return null
  if (!force && !isDataProfileRequest(message)) return null

  const startedAt = performance.now()
  logChatAgentEvent({
    surface: context?.surface ?? 'global_chat',
    agent: 'data_profiler',
    event: 'selected',
    status: 'selected',
    context,
    message_preview: previewMessage(message),
    file: fileMetadata(file),
    details: { forced: force },
  })

  try {
    const result = await chartsApi.profile({
      query: message,
      file,
      surface: context?.surface,
      run_id: context?.runId,
      session_id: context?.sessionId,
      notebook_id: context?.notebookId,
      model_id: context?.modelId,
    })
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'data_profiler',
      event: 'tool_call',
      status: 'success',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      file: fileMetadata(file),
      details: {
        rows: result.profile.rows,
        columns: result.profile.columns,
      },
    })

    // Include the table preview as plain markdown (no <details> wrapper) so
    // the LLM can read the actual row data in subsequent follow-up messages.
    return [
      result.text,
      result.table_preview
        ? `### Pré-visualização dos dados\n\n${result.table_preview}`
        : undefined,
    ].filter(Boolean).join('\n\n')
  } catch (error) {
    const errorMessage = formatApiError(error)
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'data_profiler',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      file: fileMetadata(file),
      details: { error: errorMessage },
    })
    return `Não consegui perfilar os dados. Detalhe técnico: ${errorMessage}`
  }
}
