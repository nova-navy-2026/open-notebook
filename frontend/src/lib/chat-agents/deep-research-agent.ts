import type { QueryClient } from '@tanstack/react-query'
import { researchApi } from '@/lib/api/research'
import { QUERY_KEYS } from '@/lib/api/query-client'
import type { ChatDeepResearchOptions } from '@/lib/utils/chat-agents'
import {
  logChatAgentEvent,
  previewMessage,
  type ChatAgentRunContext,
} from '@/lib/chat-agents/logger'

interface RunDeepResearchAgentParams {
  message: string
  options?: ChatDeepResearchOptions
  queryClient: QueryClient
  notebookId?: string
  context?: ChatAgentRunContext
}

export async function runDeepResearchAgent({
  message,
  options,
  queryClient,
  notebookId,
  context,
}: RunDeepResearchAgentParams): Promise<string | null> {
  if (!options) return null

  const startedAt = performance.now()
  logChatAgentEvent({
    surface: context?.surface ?? (notebookId ? 'notebook_chat' : 'global_chat'),
    agent: 'deep_research',
    event: 'selected',
    status: 'selected',
    context,
    message_preview: previewMessage(message),
    details: {
      report_type: options.reportType,
      tone: options.tone,
      notebook_id: notebookId,
      model_id: options.modelId,
    },
  })

  let result
  try {
    result = await researchApi.generateResearch({
      query: message.trim(),
      report_type: options.reportType,
      report_source: 'local',
      tone: options.tone,
      source_urls: [],
      notebook_id: notebookId,
      model_id: options.modelId,
      use_amalia: true,
      run_in_background: true,
    })
  } catch (error) {
    logChatAgentEvent({
      surface: context?.surface ?? (notebookId ? 'notebook_chat' : 'global_chat'),
      agent: 'deep_research',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: { error: error instanceof Error ? error.message : String(error) },
    })
    throw error
  }

  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.researchJobs })
  const jobId = 'job_id' in result ? result.job_id : result.id
  logChatAgentEvent({
    surface: context?.surface ?? (notebookId ? 'notebook_chat' : 'global_chat'),
    agent: 'deep_research',
    event: 'tool_call',
    status: 'success',
    context,
    duration_ms: Math.round(performance.now() - startedAt),
    details: { job_id: jobId },
  })
  const title = notebookId
    ? 'Iniciei o Deep Research para este notebook.'
    : 'Iniciei o Deep Research.'

  return [
    title,
    '',
    `- Pedido: ${message.trim()}`,
    `- Tipo: ${options.reportType}`,
    `- Escrita: ${options.tone}`,
    options.modelId ? `- Modelo: ${options.modelId}` : undefined,
    jobId ? `- Job: ${jobId}` : undefined,
    '',
    'Podes acompanhar o progresso em Relatórios Profundos > Histórico.',
  ].filter(Boolean).join('\n')
}
