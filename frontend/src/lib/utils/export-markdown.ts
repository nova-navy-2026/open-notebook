import type { SourceChatMessage } from '@/lib/types/api'

export interface ExportableConversation {
  title: string
  messages: SourceChatMessage[]
  createdAt?: string
  updatedAt?: string
}

function formatTimestamp(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function roleLabel(type: SourceChatMessage['type']): string {
  return type === 'human' ? 'Utilizador' : 'Assistente'
}

/**
 * Serialize a single conversation to a Markdown document.
 */
export function conversationToMarkdown(conversation: ExportableConversation): string {
  const lines: string[] = []
  lines.push(`# ${conversation.title || 'Conversa'}`)
  const meta: string[] = []
  if (conversation.createdAt) meta.push(`Criada: ${formatTimestamp(conversation.createdAt)}`)
  if (conversation.updatedAt) meta.push(`Atualizada: ${formatTimestamp(conversation.updatedAt)}`)
  meta.push(`Exportada: ${new Date().toLocaleString()}`)
  meta.push(`Mensagens: ${conversation.messages.length}`)
  if (meta.length) {
    lines.push('')
    lines.push(`> ${meta.join(' · ')}`)
  }

  for (const message of conversation.messages) {
    lines.push('')
    lines.push('---')
    lines.push('')
    const stamp = formatTimestamp(message.timestamp)
    lines.push(`## ${roleLabel(message.type)}${stamp ? ` — ${stamp}` : ''}`)
    if (message.attachments?.length) {
      for (const attachment of message.attachments) {
        lines.push('')
        lines.push(`*Anexo (${attachment.kind}): ${attachment.name}*`)
      }
    }
    lines.push('')
    lines.push((message.content ?? '').trim())
  }

  lines.push('')
  return lines.join('\n')
}

/**
 * Serialize many conversations into a single Markdown document.
 */
export function conversationsToMarkdown(
  conversations: ExportableConversation[],
  documentTitle = 'Conversas exportadas',
): string {
  const lines: string[] = []
  lines.push(`# ${documentTitle}`)
  lines.push('')
  lines.push(`> Total de conversas: ${conversations.length} · Exportada: ${new Date().toLocaleString()}`)

  for (const conversation of conversations) {
    lines.push('')
    lines.push('')
    lines.push('=' .repeat(3))
    lines.push('')
    lines.push(conversationToMarkdown(conversation))
  }

  lines.push('')
  return lines.join('\n')
}

function sanitizeFilename(name: string): string {
  const cleaned = name
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9-_ ]/g, '')
    .trim()
    .replace(/\s+/g, '-')
  return cleaned || 'conversa'
}

/**
 * Trigger a browser download of a Markdown string.
 */
export function downloadMarkdown(content: string, filename: string): void {
  if (typeof window === 'undefined') return
  const safeName = sanitizeFilename(filename.replace(/\.md$/i, ''))
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${safeName}.md`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
