import type { QueryClient } from '@tanstack/react-query'
import { researchApi } from '@/lib/api/research'
import { multimodalApi } from '@/lib/api/multimodal'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { MODEL_QUERY_KEYS } from '@/lib/hooks/use-models'
import { normaliseForAgentMatching, type ChatDeepResearchOptions } from '@/lib/utils/chat-agents'
import type { ResearchJob, ResearchResultData } from '@/lib/types/research'
import type { NotebookChatMessage } from '@/lib/types/api'
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
  const modelLabel = options.modelName || options.modelId

  return [
    `- Tipo: ${options.reportType}`,
    `- Escrita: ${options.tone}`,
    modelLabel ? `- Modelo: ${modelLabel}` : undefined,
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

/**
 * Prefix for the assistant message id that carries a deep research job.
 * The job id is embedded in the message id so a reload can re-attach the
 * background job to its chat message without any extra bookkeeping.
 */
export const RESEARCH_MESSAGE_ID_PREFIX = 'ai-research-'

export function researchMessageId(jobId: string): string {
  return `${RESEARCH_MESSAGE_ID_PREFIX}${jobId}`
}

export function parseResearchJobId(messageId: string | undefined | null): string | null {
  if (!messageId || !messageId.startsWith(RESEARCH_MESSAGE_ID_PREFIX)) return null
  const jobId = messageId.slice(RESEARCH_MESSAGE_ID_PREFIX.length)
  return jobId || null
}

const RESEARCH_PROGRESS_HEADER = '## Deep Research em curso'

/** A persisted research message is "in progress" while it still shows the progress header. */
export function isInProgressResearchContent(content: string): boolean {
  return content.trimStart().startsWith(RESEARCH_PROGRESS_HEADER)
}

/**
 * Resolve a model's human-readable name from its id using the cached models
 * list, so the chat shows e.g. "GPT-4o mini" instead of the raw model id.
 * Falls back to undefined (caller then shows the id) when the cache is cold.
 */
export function resolveModelName(
  queryClient: QueryClient,
  modelId?: string | null,
): string | undefined {
  if (!modelId) return undefined
  const models = queryClient.getQueryData<Array<{ id?: string; name?: string }>>(MODEL_QUERY_KEYS.models)
  if (!Array.isArray(models)) return undefined
  const match = models.find((model) => model?.id === modelId || model?.name === modelId)
  return match?.name || undefined
}

/**
 * Ensure a deep-research options object carries a human-readable model name.
 * If it only has a model id (e.g. the default model, or a router fallback),
 * resolve the name from the cached models list so the chat never shows the
 * raw model id as a "code".
 */
export function withResolvedModelName(
  options: ChatDeepResearchOptions | undefined,
  queryClient: QueryClient,
): ChatDeepResearchOptions | undefined {
  if (!options || !options.modelId || options.modelName) return options
  const modelName = resolveModelName(queryClient, options.modelId)
  return modelName ? { ...options, modelName } : options
}

/**
 * Rebuild the chat options purely from a fetched job, so a reload needs no extra
 * state. When a queryClient is supplied, the model id is resolved to its display
 * name so reconciled messages show the model name rather than the raw id.
 */
export function optionsFromJob(job: ResearchJob, queryClient?: QueryClient): ChatDeepResearchOptions {
  return {
    reportType: job.report_type,
    tone: job.tone ?? 'Objective',
    modelId: job.model_id,
    modelName: queryClient ? resolveModelName(queryClient, job.model_id) : undefined,
  }
}

const REPORT_EDIT_VERB = /\b(altera|alterar|muda|mudar|modifica|modificar|reescreve|reescrever|reformula|reformular|edita|editar|ajusta|ajustar|adiciona|adicionar|acrescenta|acrescentar|remove|remover|retira|retirar|encurta|encurtar|resume|resumir|expande|expandir|melhora|melhorar|corrige|corrigir|atualiza|atualizar|traduz|traduzir|translate|rewrite|edit|change|modify|update|shorten|expand|improve|revise|add|remove)\b/
const REPORT_NOUN = /\b(relatorio|report|pesquisa|research|texto|documento|document)\b/

/** The most recent completed deep-research report message in the conversation. */
export function findLastResearchReportMessage(messages: NotebookChatMessage[]): NotebookChatMessage | undefined {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (message.type === 'ai' && parseResearchJobId(message.id) && message.content.includes('## Deep Research concluído')) {
      return message
    }
  }
  return undefined
}

/** True when the user is asking to modify an existing deep-research report. */
export function isReportEditRequest(message: string, messages: NotebookChatMessage[]): boolean {
  if (!findLastResearchReportMessage(messages)) return false
  const text = normaliseForAgentMatching(message)
  return REPORT_EDIT_VERB.test(text) && REPORT_NOUN.test(text)
}

export interface ReportEditResult {
  targetMessageId: string
  newContent: string
}

/**
 * Edit an existing deep-research report in place instead of producing a new
 * message. Detects an edit request against the most recent report, asks the LLM
 * to return the full revised report, and rebuilds the report message (preserving
 * the job's sources/metadata) so the caller can update that same message by id.
 */
export async function runDeepResearchReportEdit({
  message,
  messages,
  queryClient,
  modelId,
  context,
}: {
  message: string
  messages: NotebookChatMessage[]
  queryClient: QueryClient
  modelId?: string
  context?: ChatAgentRunContext
}): Promise<ReportEditResult | null> {
  const target = findLastResearchReportMessage(messages)
  if (!target || !isReportEditRequest(message, messages)) return null
  const jobId = parseResearchJobId(target.id)
  if (!jobId) return null

  const startedAt = performance.now()
  const surface = context?.surface ?? 'global_chat'
  logChatAgentEvent({
    surface,
    agent: 'deep_research',
    event: 'selected',
    status: 'selected',
    context,
    message_preview: previewMessage(message),
    details: { mode: 'report_edit', job_id: jobId },
  })

  let job: ResearchJob
  try {
    job = await researchApi.getJob(jobId)
  } catch {
    return null
  }
  const currentReport = job.result?.report?.trim()
  if (!currentReport) return null

  const prompt = [
    'Tens um relatório existente em Markdown (no Contexto abaixo).',
    'Aplica a alteração pedida pelo utilizador e devolve APENAS o relatório COMPLETO e atualizado,',
    'no mesmo formato Markdown e na mesma língua do original.',
    'Não acrescentes comentários, títulos extra, nem expliques o que mudaste — devolve só o relatório.',
    '',
    `Alteração pedida: ${message.trim()}`,
  ].join('\n')

  let editedReport: string
  try {
    const result = await multimodalApi.chat({
      query: prompt,
      context: currentReport,
      mode: 'chat',
      model_id: modelId,
      surface,
      run_id: context?.runId,
      session_id: context?.sessionId,
      notebook_id: context?.notebookId,
    })
    editedReport = (result.text || '').trim()
  } catch (error) {
    logChatAgentEvent({
      surface,
      agent: 'deep_research',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: { mode: 'report_edit', error: error instanceof Error ? error.message : String(error) },
    })
    throw error
  }
  if (!editedReport) return null

  const editedJob: ResearchJob = {
    ...job,
    result: { ...(job.result as ResearchResultData), report: editedReport },
  }
  const newContent = formatDeepResearchResult(job.query, optionsFromJob(job, queryClient), editedJob)
  logChatAgentEvent({
    surface,
    agent: 'deep_research',
    event: 'tool_call',
    status: 'success',
    context,
    duration_ms: Math.round(performance.now() - startedAt),
    details: { mode: 'report_edit', job_id: jobId, response_chars: editedReport.length },
  })
  return { targetMessageId: target.id, newContent }
}

interface ReconcileDeepResearchParams {
  messages: NotebookChatMessage[]
  /** Shared set (kept in a ref) of job ids already being polled by this hook instance. */
  polledJobs: Set<string>
  queryClient: QueryClient
  /** Whether the conversation owning these messages is still the active one. */
  isActive: () => boolean
  applyContent: (messageId: string, content: string) => void
  persist: (args: {
    userMessage: string
    userMessageId?: string
    assistantMessage: string
    assistantMessageId: string
  }) => void
}

/**
 * Re-attach background deep research jobs to their chat messages after a reload
 * or navigation. For every "em curso" research message that isn't already being
 * polled by this hook instance, resume polling and rewrite/persist the message
 * when the job advances, completes, or fails. Everything needed is rebuilt from
 * the fetched job, so no per-message state has to survive the page change.
 */
export function reconcileDeepResearchMessages({
  messages,
  polledJobs,
  queryClient,
  isActive,
  applyContent,
  persist,
}: ReconcileDeepResearchParams): void {
  messages.forEach((message, index) => {
    if (message.type !== 'ai') return
    const jobId = parseResearchJobId(message.id)
    if (!jobId) return
    if (polledJobs.has(jobId)) return
    if (!isInProgressResearchContent(message.content)) return

    polledJobs.add(jobId)
    const assistantMessageId = message.id
    const previous = messages[index - 1]
    const userMessage = previous && previous.type === 'human' ? previous.content : ''
    const userMessageId = previous && previous.type === 'human' ? previous.id : undefined

    void pollDeepResearchJob({
      jobId,
      queryClient,
      onUpdate: (_content, job) => {
        if (!isActive()) return
        applyContent(assistantMessageId, formatDeepResearchProgress(job.query, optionsFromJob(job, queryClient), jobId, job))
      },
      onComplete: (_content, job) => {
        const content = formatDeepResearchResult(job.query, optionsFromJob(job, queryClient), job)
        if (isActive()) applyContent(assistantMessageId, content)
        persist({ userMessage, userMessageId, assistantMessage: content, assistantMessageId })
      },
      onFailure: (_content, job) => {
        // No job means a transient transport error (or timeout): don't burn the
        // message into a permanent failure — allow a later reconcile to retry.
        if (!job) {
          polledJobs.delete(jobId)
          return
        }
        const content = formatDeepResearchFailure(job.query || userMessage, optionsFromJob(job, queryClient), jobId, job.error)
        if (isActive()) applyContent(assistantMessageId, content)
        persist({ userMessage, userMessageId, assistantMessage: content, assistantMessageId })
      },
    }).catch((pollError) => {
      polledJobs.delete(jobId)
      console.error('Failed to reconcile deep research job:', pollError)
    })
  })
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
