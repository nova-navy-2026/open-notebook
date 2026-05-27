'use client'

import { useState, useCallback } from 'react'
import { toast } from 'sonner'
import { chatApi } from '@/lib/api/chat'
import { multimodalApi } from '@/lib/api/multimodal'
import { SourceListResponse, NoteResponse } from '@/lib/types/api'
import { ContextSelections } from '@/app/(dashboard)/notebooks/[id]/page'
import { NotebookChatMessage } from '@/lib/types/api'

interface UseMultimodalChatParams {
  notebookId: string
  sources: SourceListResponse[]
  notes: NoteResponse[]
  contextSelections: ContextSelections
  selectedNavyDocIds?: Set<string>
}

function formatContext(context: {
  sources: Array<Record<string, unknown>>
  notes: Array<Record<string, unknown>>
  navy_corpus?: Array<Record<string, unknown>>
}): string {
  const parts: string[] = []

  for (const item of context.sources) {
    const title = (item.title as string) || (item.id as string) || 'Source'
    const content = (item.content as string) || ''
    if (content.trim()) {
      parts.push(`[Source – ${title}]:\n${content}`)
    }
  }

  for (const item of context.notes) {
    const title = (item.title as string) || 'Note'
    const content = (item.content as string) || ''
    if (content.trim()) {
      parts.push(`[Note – ${title}]:\n${content}`)
    }
  }

  if (context.navy_corpus) {
    for (const item of context.navy_corpus) {
      const title = (item.title as string) || 'Document chunk'
      const content = (item.content as string) || ''
      if (content.trim()) {
        parts.push(`[Document – ${title}]:\n${content}`)
      }
    }
  }

  return parts.join('\n\n')
}

export function useMultimodalChat({
  notebookId,
  sources,
  notes,
  contextSelections,
  selectedNavyDocIds,
}: UseMultimodalChatParams) {
  const [messages, setMessages] = useState<NotebookChatMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [tokenCount, setTokenCount] = useState(0)
  const [charCount, setCharCount] = useState(0)

  const buildContext = useCallback(
    async (query?: string) => {
      const context_config: {
        sources: Record<string, string>
        notes: Record<string, string>
        navy_docs?: { doc_ids: string[] }
      } = { sources: {}, notes: {} }

      sources.forEach((source) => {
        const mode = contextSelections.sources[source.id]
        if (mode === 'insights') {
          context_config.sources[source.id] = 'insights'
        } else if (mode === 'full') {
          context_config.sources[source.id] = 'full content'
        } else {
          context_config.sources[source.id] = 'not in'
        }
      })

      notes.forEach((note) => {
        const mode = contextSelections.notes[note.id]
        if (mode === 'full') {
          context_config.notes[note.id] = 'full content'
        } else {
          context_config.notes[note.id] = 'not in'
        }
      })

      if (selectedNavyDocIds && selectedNavyDocIds.size > 0) {
        context_config.navy_docs = { doc_ids: Array.from(selectedNavyDocIds) }
      }

      const response = await chatApi.buildContext({
        notebook_id: notebookId,
        context_config,
        ...(query ? { query } : {}),
      })

      setTokenCount(response.token_count)
      setCharCount(response.char_count)

      return response.context
    },
    [notebookId, sources, notes, contextSelections, selectedNavyDocIds],
  )

  const sendMessage = useCallback(
    async (message: string, file?: File) => {
      const userMessage: NotebookChatMessage = {
        id: `temp-${Date.now()}`,
        type: 'human',
        content: message,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, userMessage])
      setIsSending(true)

      try {
        const rawContext = await buildContext(message)
        const contextText = formatContext(rawContext)

        const result = await multimodalApi.chat({
          query: message,
          context: contextText || undefined,
          mode: 'chat',
          file,
        })

        const aiMessage: NotebookChatMessage = {
          id: `ai-${Date.now()}`,
          type: 'ai',
          content: result.text,
          timestamp: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, aiMessage])
      } catch (err: unknown) {
        const error = err as { response?: { data?: { detail?: string } }; message?: string }
        console.error('Multimodal chat error:', error)
        toast.error(error.response?.data?.detail || error.message || 'Failed to send message')
        setMessages((prev) =>
          prev.filter((m) => !m.id.startsWith('temp-') && !m.id.startsWith('ai-')),
        )
      } finally {
        setIsSending(false)
      }
    },
    [buildContext],
  )

  const clearMessages = useCallback(() => {
    setMessages([])
  }, [])

  return {
    messages,
    isSending,
    tokenCount,
    charCount,
    sendMessage,
    clearMessages,
    buildContext,
  }
}
