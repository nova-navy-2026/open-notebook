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

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * Render the message body as Word-friendly HTML. The content is treated as
 * plain text (escaped) with blank lines becoming paragraph breaks and single
 * line breaks preserved — this keeps the document structured without pulling in
 * a full Markdown renderer.
 */
function renderBody(content: string): string {
  const text = (content ?? '').trim()
  if (!text) return '<p class="empty">—</p>'
  return text
    .split(/\n{2,}/)
    .map(
      (paragraph) =>
        `<p>${escapeHtml(paragraph).replace(/\n/g, '<br/>')}</p>`,
    )
    .join('\n')
}

function renderMessage(message: SourceChatMessage): string {
  const stamp = formatTimestamp(message.timestamp)
  const isHuman = message.type === 'human'
  const parts: string[] = []
  parts.push(
    `<h2 class="turn ${isHuman ? 'turn-human' : 'turn-ai'}">${escapeHtml(
      roleLabel(message.type),
    )}${stamp ? ` <span class="stamp">— ${escapeHtml(stamp)}</span>` : ''}</h2>`,
  )
  if (message.attachments?.length) {
    for (const attachment of message.attachments) {
      parts.push(
        `<p class="attachment"><em>Anexo (${escapeHtml(
          attachment.kind,
        )}): ${escapeHtml(attachment.name)}</em></p>`,
      )
    }
  }
  parts.push(renderBody(message.content))
  return parts.join('\n')
}

function renderConversation(
  conversation: ExportableConversation,
  headingLevel: 'h1' | 'h2' = 'h1',
): string {
  const meta: string[] = []
  if (conversation.createdAt)
    meta.push(`Criada: ${formatTimestamp(conversation.createdAt)}`)
  if (conversation.updatedAt)
    meta.push(`Atualizada: ${formatTimestamp(conversation.updatedAt)}`)
  meta.push(`Exportada: ${new Date().toLocaleString()}`)
  meta.push(`Mensagens: ${conversation.messages.length}`)

  const parts: string[] = []
  parts.push(
    `<${headingLevel} class="conversation-title">${escapeHtml(
      conversation.title || 'Conversa',
    )}</${headingLevel}>`,
  )
  parts.push(`<p class="meta">${escapeHtml(meta.join(' · '))}</p>`)
  for (const message of conversation.messages) {
    parts.push('<hr/>')
    parts.push(renderMessage(message))
  }
  return parts.join('\n')
}

const DOC_STYLES = `
  body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; color: #1a1a1a; }
  h1 { font-size: 20pt; margin: 0 0 4pt 0; }
  h1.document-title { border-bottom: 2px solid #1f3a5f; padding-bottom: 6pt; }
  h1.conversation-title { font-size: 16pt; color: #1f3a5f; }
  h2.turn { font-size: 12pt; margin: 14pt 0 2pt 0; }
  h2.turn-human { color: #1f3a5f; }
  h2.turn-ai { color: #2f6f4f; }
  .stamp { font-weight: normal; font-size: 9pt; color: #777; }
  .meta { font-size: 9pt; color: #666; margin: 0 0 10pt 0; }
  .attachment { font-size: 10pt; color: #555; }
  .empty { color: #999; }
  p { margin: 4pt 0; line-height: 1.4; }
  hr { border: none; border-top: 1px solid #ddd; margin: 12pt 0; }
`

function wrapDocument(title: string, bodyHtml: string): string {
  // Word opens HTML documents saved as .doc and honours the office namespaces.
  return `<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
<head>
  <meta charset="utf-8"/>
  <title>${escapeHtml(title)}</title>
  <style>${DOC_STYLES}</style>
</head>
<body>
${bodyHtml}
</body>
</html>`
}

/**
 * Serialize a single conversation to a Word-compatible document string.
 */
export function conversationToDocx(conversation: ExportableConversation): string {
  return wrapDocument(
    conversation.title || 'Conversa',
    renderConversation(conversation, 'h1'),
  )
}

/**
 * Serialize many conversations into a single Word-compatible document string.
 */
export function conversationsToDocx(
  conversations: ExportableConversation[],
  documentTitle = 'Conversas exportadas',
): string {
  const parts: string[] = []
  parts.push(
    `<h1 class="document-title">${escapeHtml(documentTitle)}</h1>`,
  )
  parts.push(
    `<p class="meta">${escapeHtml(
      `Total de conversas: ${conversations.length} · Exportada: ${new Date().toLocaleString()}`,
    )}</p>`,
  )
  conversations.forEach((conversation) => {
    parts.push('<br/>')
    parts.push(renderConversation(conversation, 'h2'))
  })
  return wrapDocument(documentTitle, parts.join('\n'))
}

function sanitizeFilename(name: string): string {
  const cleaned = name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-zA-Z0-9-_ ]/g, '')
    .trim()
    .replace(/\s+/g, '-')
  return cleaned || 'conversa'
}

/**
 * Trigger a browser download of a Word document (.doc).
 */
export function downloadDocx(content: string, filename: string): void {
  if (typeof window === 'undefined') return
  const safeName = sanitizeFilename(filename.replace(/\.docx?$/i, ''))
  const blob = new Blob(['﻿', content], {
    type: 'application/msword;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${safeName}.doc`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
