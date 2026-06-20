import type { QueryClient } from '@tanstack/react-query'
import { notebooksApi } from '@/lib/api/notebooks'
import { notesApi } from '@/lib/api/notes'
import { QUERY_KEYS } from '@/lib/api/query-client'
import type { NotebookChatMessage, NotebookResponse } from '@/lib/types/api'
import {
  isSaveToNoteRequest,
  normaliseForAgentMatching,
  parseMessageOrdinalFromEnd,
  parseSaveToNoteTarget,
  selectTargetAssistantMessage,
} from '@/lib/utils/chat-agents'
import {
  logChatAgentEvent,
  previewMessage,
  type ChatAgentRunContext,
} from '@/lib/chat-agents/logger'

function findNotebookForSave(
  notebooks: NotebookResponse[],
  target?: string,
  targetId?: string,
): NotebookResponse | undefined {
  const activeNotebooks = notebooks.filter((notebook) => !notebook.archived)
  if (targetId) {
    return activeNotebooks.find((notebook) => notebook.id === targetId)
  }
  if (!target) return activeNotebooks.length === 1 ? activeNotebooks[0] : undefined

  const wanted = normaliseForAgentMatching(target)
  return activeNotebooks.find((notebook) => {
    const name = normaliseForAgentMatching(notebook.name)
    const id = normaliseForAgentMatching(notebook.id)
    return (
      name === wanted
      || name.includes(wanted)
      || wanted.includes(name)
      || id === wanted
      || id.endsWith(wanted)
    )
  })
}

function parseRequestedTitle(message: string): string | undefined {
  const patterns = [
    /\b(?:titulo|título|title)\s*[:=]\s*["“”']?([^"“”'\n]+)["“”']?/i,
    /\b(?:como|as)\s+["“”']([^"“”']+)["“”']/i,
    /\b(?:chamada|chamado|called|named)\s+["“”']([^"“”']+)["“”']/i,
  ]
  for (const pattern of patterns) {
    const match = message.match(pattern)
    const title = match?.[1]?.trim()
    if (title) return title.slice(0, 120)
  }
  return undefined
}

function firstMarkdownTable(content: string): string | undefined {
  const lines = content.split(/\r?\n/)
  for (let index = 0; index < lines.length - 1; index++) {
    if (
      lines[index].trim().startsWith('|') &&
      lines[index + 1].trim().startsWith('|') &&
      /-{3,}/.test(lines[index + 1])
    ) {
      const table: string[] = []
      for (let cursor = index; cursor < lines.length; cursor++) {
        const line = lines[cursor]
        if (!line.trim().startsWith('|')) break
        table.push(line)
      }
      return table.join('\n')
    }
  }
  return undefined
}

function extractReportBody(content: string): string | undefined {
  const marker = '## Deep Research concluído'
  const start = content.indexOf(marker)
  if (start < 0) return undefined
  const sources = content.indexOf('\n## Fontes', start + marker.length)
  return content.slice(start, sources > 0 ? sources : undefined).trim()
}

function selectContentForSave(message: string, previous: NotebookChatMessage): string {
  const text = normaliseForAgentMatching(message)
  if (/\b(tabela|table|csv)\b/.test(text)) {
    const table = firstMarkdownTable(previous.content)
    if (table) return table
  }
  if (/\b(relatorio|relatório|report|deep research)\b/.test(text)) {
    const report = extractReportBody(previous.content)
    if (report) return report
  }
  return previous.content
}

function noteTitleForSave(message: string, fallback: string): string {
  return parseRequestedTitle(message) || fallback
}

/** Human-readable (pt-PT) description of which message was saved, counted from the end. */
function describeMessagePosition(fromEnd: number): string {
  if (fromEnd <= 1) return 'última resposta'
  if (fromEnd === 2) return 'penúltima resposta'
  if (fromEnd === 3) return 'antepenúltima resposta'
  return `${fromEnd}ª resposta a contar do fim`
}

export async function runGlobalSaveNoteAgent({
  message,
  messages,
  queryClient,
  context,
  force = false,
  targetNotebookId,
}: {
  message: string
  messages: NotebookChatMessage[]
  queryClient: QueryClient
  context?: ChatAgentRunContext
  force?: boolean
  targetNotebookId?: string
}): Promise<string | null> {
  if (!force && !isSaveToNoteRequest(message)) return null

  const startedAt = performance.now()
  logChatAgentEvent({
    surface: context?.surface ?? 'global_chat',
    agent: 'save_note',
    event: 'selected',
    status: 'selected',
    context,
    message_preview: previewMessage(message),
  })

  const previous = selectTargetAssistantMessage(message, messages)
  const positionLabel = describeMessagePosition(parseMessageOrdinalFromEnd(message))
  const notebooks = await notebooksApi.list({ archived: false })
  const target = parseSaveToNoteTarget(message)
  const targetNotebook = findNotebookForSave(notebooks, target, targetNotebookId)

  if (!previous) {
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'save_note',
      event: 'validation',
      status: 'skipped',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: { reason: 'no_previous_assistant_message' },
    })
    return 'Ainda não há uma resposta anterior para guardar como nota.'
  }

  if (!targetNotebook) {
    const options = notebooks
      .filter((notebook) => !notebook.archived)
      .map((notebook) => `- ${notebook.name}`)
      .join('\n')
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'save_note',
      event: 'validation',
      status: 'skipped',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: {
        reason: 'target_notebook_missing',
        requested_target: target,
        available_notebooks: notebooks.filter((notebook) => !notebook.archived).length,
      },
    })
    return target
      ? `Não encontrei um notebook chamado "${target}". Indica um destes notebooks:\n\n${options || '- Nenhum notebook disponível'}`
      : `Preciso de saber em que notebook queres guardar a nota. Indica um destes notebooks:\n\n${options || '- Nenhum notebook disponível'}`
  }

  let note
  try {
    const content = selectContentForSave(message, previous)
    note = await notesApi.create({
      notebook_id: targetNotebook.id,
      title: noteTitleForSave(message, 'Nota criada a partir do chat'),
      content,
      note_type: 'ai',
    })
  } catch (error) {
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'save_note',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: { error: error instanceof Error ? error.message : String(error) },
    })
    throw error
  }
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notes(targetNotebook.id) })
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
  logChatAgentEvent({
    surface: context?.surface ?? 'global_chat',
    agent: 'save_note',
    event: 'tool_call',
    status: 'success',
    context,
    duration_ms: Math.round(performance.now() - startedAt),
    details: { notebook_id: targetNotebook.id, note_id: note.id, message_position: positionLabel },
  })
  return `Guardei a ${positionLabel} como nota em "${targetNotebook.name}": ${note.title || note.id}.`
}

export async function runNotebookSaveNoteAgent({
  message,
  messages,
  notebookId,
  queryClient,
  context,
  force = false,
}: {
  message: string
  messages: NotebookChatMessage[]
  notebookId: string
  queryClient: QueryClient
  context?: ChatAgentRunContext
  force?: boolean
}): Promise<string | null> {
  if (!force && !isSaveToNoteRequest(message)) return null

  const startedAt = performance.now()
  logChatAgentEvent({
    surface: context?.surface ?? 'notebook_chat',
    agent: 'save_note',
    event: 'selected',
    status: 'selected',
    context,
    message_preview: previewMessage(message),
    details: { notebook_id: notebookId },
  })

  const previous = selectTargetAssistantMessage(message, messages)
  const positionLabel = describeMessagePosition(parseMessageOrdinalFromEnd(message))
  if (!previous) {
    logChatAgentEvent({
      surface: context?.surface ?? 'notebook_chat',
      agent: 'save_note',
      event: 'validation',
      status: 'skipped',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: { reason: 'no_previous_assistant_message' },
    })
    return 'Ainda não há uma resposta anterior para guardar como nota.'
  }

  let note
  try {
    const content = selectContentForSave(message, previous)
    note = await notesApi.create({
      notebook_id: notebookId,
      title: noteTitleForSave(message, 'Nota criada a partir do chat'),
      content,
      note_type: 'ai',
    })
  } catch (error) {
    logChatAgentEvent({
      surface: context?.surface ?? 'notebook_chat',
      agent: 'save_note',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: { error: error instanceof Error ? error.message : String(error) },
    })
    throw error
  }
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notes(notebookId) })
  logChatAgentEvent({
    surface: context?.surface ?? 'notebook_chat',
    agent: 'save_note',
    event: 'tool_call',
    status: 'success',
    context,
    duration_ms: Math.round(performance.now() - startedAt),
    details: { notebook_id: notebookId, note_id: note.id, message_position: positionLabel },
  })
  return `Guardei a ${positionLabel} como nota neste notebook: ${note.title || note.id}.`
}
