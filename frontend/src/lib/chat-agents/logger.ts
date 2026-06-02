import { chatAgentLogsApi } from '@/lib/api/chat-agent-logs'
import type { ChatAgentLogPayload } from '@/lib/api/chat-agent-logs'

export interface ChatAgentRunContext {
  surface: ChatAgentLogPayload['surface']
  runId?: string
  sessionId?: string
  notebookId?: string
  modelId?: string
}

export function createChatAgentRunId(surface: ChatAgentRunContext['surface']): string {
  const randomId = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  return `${surface}:${randomId}`
}

export function previewMessage(message: string, limit = 180): string {
  const compact = message.replace(/\s+/g, ' ').trim()
  return compact.length > limit ? `${compact.slice(0, limit)}...` : compact
}

export function fileMetadata(file?: File | null): ChatAgentLogPayload['file'] | undefined {
  if (!file) return undefined
  return {
    name: file.name,
    type: file.type,
    size: file.size,
  }
}

export function logChatAgentEvent(
  payload: Omit<ChatAgentLogPayload, 'session_id' | 'notebook_id' | 'model_id'>
    & { context?: ChatAgentRunContext },
): void {
  const { context, ...event } = payload
  void chatAgentLogsApi.log({
    ...event,
    run_id: context?.runId,
    session_id: context?.sessionId,
    notebook_id: context?.notebookId,
    model_id: context?.modelId,
  }).catch((error) => {
    console.debug('Failed to write chat-agent log event:', error)
  })
}
