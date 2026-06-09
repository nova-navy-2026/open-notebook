import type { QueryClient } from '@tanstack/react-query'
import { researchApi } from '@/lib/api/research'
import { QUERY_KEYS } from '@/lib/api/query-client'
import type { ChatDeepResearchOptions } from '@/lib/utils/chat-agents'
import type { ResearchJob, ResearchResultData } from '@/lib/types/research'
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

export interface DeepResearchRun {
  jobId: string
  initialContent: string
}

interface PollDeepResearchJobParams {
  jobId: string
  queryClient: QueryClient
  onUpdate: (content: string, job: ResearchJob) => void
  onComplete: (content: string, job: ResearchJob) => void
  onFailure: (content: string, job?: ResearchJob) => void
  intervalMs?: number
  timeoutMs?: number
}

function formatOptions(options: ChatDeepResearchOptions): string[] {
  return [
    `- Tipo: ${options.reportType}`,
    `- Escrita: ${options.tone}`,
    options.modelId ? `- Modelo: ${options.modelId}` : undefined,
  ].filter(Boolean) as string[]
}

export function formatDeepResearchProgress(
  message: string,
  options: ChatDeepResearchOptions,
  jobId: string,
  job?: ResearchJob,
): string {
  const status = job?.status ?? 'pending'
  const progress = job?.progress || 'A preparar o plano de investigação...'
  const pct = typeof job?.progress_pct === 'number' ? ` (${job.progress_pct}%)` : ''

  return [
    '## Deep Research em curso',
    '',
    `**Pedido:** ${message.trim()}`,
    '',
    ...formatOptions(options),
    `- Job: ${jobId}`,
    `- Estado: ${status}${pct}`,
    '',
    progress,
    '',
    'Podes continuar a conversar aqui. Quando o relatório terminar, eu atualizo esta mensagem. Também fica guardado em Deep Research > Histórico.',
  ].join('\n')
}

function formatSources(result?: ResearchResultData | null): string[] {
  const docs = result?.retrieved_documents ?? []
  const urls = result?.source_urls ?? []
  const lines: string[] = []

  if (docs.length > 0) {
    lines.push('## Fontes')
    docs.slice(0, 12).forEach((doc, index) => {
      const title = doc.title || doc.source || `Fonte ${index + 1}`
      lines.push(`- ${doc.source ? `[${title}](${doc.source})` : title}`)
    })
  } else if (urls.length > 0) {
    lines.push('## Fontes')
    urls.slice(0, 12).forEach((url) => {
      lines.push(`- ${url}`)
    })
  }

  return lines
}

export function formatDeepResearchResult(
  message: string,
  options: ChatDeepResearchOptions,
  job: ResearchJob,
): string {
  const report = job.result?.report?.trim()
  const reportBody = report || 'O job terminou, mas não devolveu texto de relatório.'
  const sourceLines = formatSources(job.result)

  return [
    '## Deep Research concluído',
    '',
    `**Pedido:** ${message.trim()}`,
    '',
    ...formatOptions(options),
    `- Job: ${job.id}`,
    job.result?.research_costs ? `- Custo estimado: ${job.result.research_costs}` : undefined,
    '',
    reportBody,
    '',
    ...sourceLines,
    '',
    'Este relatório também ficou guardado em Deep Research > Histórico.',
  ].filter(Boolean).join('\n')
}

export function formatDeepResearchFailure(
  message: string,
  options: ChatDeepResearchOptions,
  jobId: string,
  error?: string | null,
): string {
  return [
    '## Deep Research falhou',
    '',
    `**Pedido:** ${message.trim()}`,
    '',
    ...formatOptions(options),
    `- Job: ${jobId}`,
    '',
    error || 'O job terminou com erro, mas não devolveu detalhe técnico.',
    '',
    'Podes tentar novamente ou abrir o histórico de Deep Research para ver o estado do job.',
  ].join('\n')
}

export async function runDeepResearchAgent({
  message,
  options,
  queryClient,
  notebookId,
  context,
}: RunDeepResearchAgentParams): Promise<DeepResearchRun | null> {
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
  return {
    jobId,
    initialContent: formatDeepResearchProgress(message, options, jobId),
  }
}

export async function pollDeepResearchJob({
  jobId,
  queryClient,
  onUpdate,
  onComplete,
  onFailure,
  intervalMs = 3000,
  timeoutMs = 45 * 60 * 1000,
}: PollDeepResearchJobParams): Promise<void> {
  const startedAt = Date.now()
  let lastProgress = ''

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const job = await researchApi.getJob(jobId)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.researchJobs })
      queryClient.setQueryData(QUERY_KEYS.researchJob(jobId), job)

      const progressKey = `${job.status}:${job.progress_pct}:${job.progress}`
      if (progressKey !== lastProgress) {
        lastProgress = progressKey
        onUpdate('', job)
      }

      if (job.status === 'completed') {
        onComplete('', job)
        return
      }

      if (job.status === 'failed') {
        onFailure('', job)
        return
      }
    } catch (error) {
      onFailure(error instanceof Error ? error.message : String(error))
      return
    }

    await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
  }

  onFailure('O Deep Research demorou demasiado tempo a responder. O job pode continuar ativo no Histórico.')
}
