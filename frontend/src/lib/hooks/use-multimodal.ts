'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { chatApi } from '@/lib/api/chat'
import { multimodalApi } from '@/lib/api/multimodal'
import { SourceListResponse, NoteResponse } from '@/lib/types/api'
import { ContextSelections } from '@/app/(dashboard)/notebooks/[id]/page'
import { NotebookChatMessage } from '@/lib/types/api'
import type { MultimodalResponse } from '@/lib/api/multimodal'
import { runDeepResearchAgent } from '@/lib/chat-agents/deep-research-agent'
import { runNotebookSaveNoteAgent } from '@/lib/chat-agents/save-note-agent'
import { runRouteAgent } from '@/lib/chat-agents/route-agent'
import { runTranscriptionAgent } from '@/lib/chat-agents/transcription-agent'
import { fileMetadata, logChatAgentEvent, previewMessage } from '@/lib/chat-agents/logger'
import { routeChatAgentWithGemma } from '@/lib/chat-agents/router'
import {
  applyTextAgentInstruction,
  detectTextAgentInstruction,
  instructionForAgent,
} from '@/lib/utils/chat-agents'
import { getAttachmentKind, isVisualLikeFile } from '@/lib/utils/file-kind'
import type { ChatAgentUiOptions, ChatDeepResearchOptions } from '@/lib/utils/chat-agents'

interface UseMultimodalChatParams {
  notebookId: string
  sources: SourceListResponse[]
  notes: NoteResponse[]
  contextSelections: ContextSelections
  selectedNavyDocIds?: Set<string>
}

function storageKeyForNotebook(notebookId: string): string {
  return `open-notebook:notebook:${notebookId}:multimodal-chat`
}

function serialisableMessages(messages: NotebookChatMessage[]): NotebookChatMessage[] {
  return messages.map((message) => ({ ...message, attachments: undefined }))
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

function createAttachment(file?: File): NotebookChatMessage['attachments'] {
  if (!file) return undefined
  return [{ name: file.name, url: URL.createObjectURL(file), kind: getAttachmentKind(file) }]
}

function isVisualFile(file?: File | null): file is File {
  return isVisualLikeFile(file)
}

function normaliseForMatching(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

function looksLikeVisualFollowUp(message: string): boolean {
  const text = normaliseForMatching(message)
  return /\b(image|picture|photo|foto|imagem|video|frame|ocr|texto|text|ler|read|extrair|extract|transcrever|transcribe|detetar|detectar|detect|identifica|identificar|identify|conta|contar|count|segment|segmenta|segmentar|sam-?3|rf-?\s?detr|rfdetr|again|de novo|outra vez|anexo|ficheiro)\b/.test(text)
}

function buildVisualContext(previousResponse: string): string | undefined {
  if (!previousResponse.trim()) return undefined
  return `Última análise visual:\n${previousResponse.trim()}`
}

async function formatMultimodalResponse(result: MultimodalResponse): Promise<string> {
  const parts = [result.text]

  if (result.image_base64) {
    const imageUrl = await multimodalApi.saveNoteAsset(result.image_base64).catch(() => result.image_base64)
    parts.push(`![Resultado da análise visual](${imageUrl})`)
  }

  if (result.video_base64) {
    const videoUrl = await multimodalApi.saveNoteAsset(result.video_base64).catch(() => result.video_base64)
    parts.push(`[Vídeo anotado](${videoUrl})`)
  }

  return parts.filter((part) => part && part.trim()).join('\n\n')
}

export function useMultimodalChat({
  notebookId,
  sources,
  notes,
  contextSelections,
  selectedNavyDocIds,
}: UseMultimodalChatParams) {
  const queryClient = useQueryClient()
  const [messages, setMessages] = useState<NotebookChatMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [tokenCount, setTokenCount] = useState(0)
  const [charCount, setCharCount] = useState(0)
  const lastVisualFileRef = useRef<File | null>(null)
  const lastVisualQueryRef = useRef('')
  const lastVisualContextRef = useRef('')
  const storageReadyRef = useRef(false)

  useEffect(() => {
    storageReadyRef.current = false
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''

    if (typeof window === 'undefined') {
      storageReadyRef.current = true
      return
    }

    const stored = window.localStorage.getItem(storageKeyForNotebook(notebookId))
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as NotebookChatMessage[]
        setMessages(Array.isArray(parsed) ? parsed : [])
      } catch (error) {
        console.error('Failed to restore multimodal notebook chat:', error)
        setMessages([])
      }
    } else {
      setMessages([])
    }
    window.setTimeout(() => {
      storageReadyRef.current = true
    }, 0)
  }, [notebookId])

  useEffect(() => {
    if (!storageReadyRef.current || typeof window === 'undefined') return
    const key = storageKeyForNotebook(notebookId)
    if (messages.length === 0) {
      window.localStorage.removeItem(key)
      return
    }
    window.localStorage.setItem(key, JSON.stringify(serialisableMessages(messages)))
  }, [messages, notebookId])

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
    async (
      message: string,
      file?: File,
      deepResearch?: ChatDeepResearchOptions,
      agentOptions?: ChatAgentUiOptions,
    ) => {
      const isVisualFollowUp = !file && isVisualFile(lastVisualFileRef.current) && looksLikeVisualFollowUp(message)
      const visualFile = file ?? (isVisualFollowUp ? lastVisualFileRef.current ?? undefined : undefined)
      const visualQuery = message

      const userMessage: NotebookChatMessage = {
        id: `temp-${Date.now()}`,
        type: 'human',
        content: file
          ? `${message}\n\n[Anexo: ${file.name}]`
          : isVisualFollowUp && visualFile
            ? `${message}\n\n[Imagem anterior: ${visualFile.name}]`
            : message,
        attachments: createAttachment(file ?? (isVisualFollowUp ? visualFile : undefined)),
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, userMessage])
      setIsSending(true)

      try {
        const agentContext = {
          surface: 'notebook_chat' as const,
          notebookId,
        }
        const routerDecision = await routeChatAgentWithGemma({
          message,
          file: visualFile,
          visualFollowUp: isVisualFollowUp,
          deepResearchEnabled: Boolean(deepResearch),
          context: agentContext,
        })
        const preferredAgent = routerDecision && routerDecision.confidence >= 0.55
          ? routerDecision.agent
          : undefined

        if (!file) {
          const content = await runDeepResearchAgent({
            message,
            options: deepResearch,
            queryClient,
            notebookId,
            context: agentContext,
          })
          if (content) {
            const aiMessage: NotebookChatMessage = {
              id: `ai-${Date.now()}`,
              type: 'ai',
              content,
              timestamp: new Date().toISOString(),
            }
            setMessages((prev) => [...prev, aiMessage])
            return
          }
        }

        if (!file) {
          const content = await runNotebookSaveNoteAgent({
            message,
            messages,
            notebookId,
            queryClient,
            context: agentContext,
            force: preferredAgent === 'save_note',
          })
          if (content) {
            const aiMessage: NotebookChatMessage = {
              id: `ai-${Date.now()}`,
              type: 'ai',
              content,
              timestamp: new Date().toISOString(),
            }
            setMessages((prev) => [...prev, aiMessage])
            return
          }
        }

        if (!file) {
          const content = await runRouteAgent(
            message,
            agentContext,
            preferredAgent === 'route' ? routerDecision?.parameters : undefined,
          )
          if (content) {
            const aiMessage: NotebookChatMessage = {
              id: `ai-${Date.now()}`,
              type: 'ai',
              content,
              timestamp: new Date().toISOString(),
            }
            setMessages((prev) => [...prev, aiMessage])
            return
          }
        }

        if (file) {
          const content = await runTranscriptionAgent(
            message,
            file,
            agentContext,
            preferredAgent === 'transcription',
            agentOptions?.transcription,
          )
          if (content) {
            const aiMessage: NotebookChatMessage = {
              id: `ai-${Date.now()}`,
              type: 'ai',
              content,
              timestamp: new Date().toISOString(),
            }
            setMessages((prev) => [...prev, aiMessage])
            return
          }
        }

        const instruction = routerDecision?.instruction || instructionForAgent(preferredAgent) || detectTextAgentInstruction(visualQuery)
        if (instruction) {
          logChatAgentEvent({
            surface: 'notebook_chat',
            agent: 'text_instruction',
            event: 'selected',
            status: 'selected',
            context: agentContext,
            message_preview: previewMessage(message),
            details: { instruction: instruction.split('\n')[0] },
          })
        }

        const startedAt = performance.now()
        if (isVisualFile(visualFile)) {
          logChatAgentEvent({
            surface: 'notebook_chat',
            agent: 'multimodal',
            event: 'selected',
            status: 'selected',
            context: agentContext,
            message_preview: previewMessage(message),
            file: fileMetadata(visualFile),
            details: {
              follow_up: isVisualFollowUp,
              has_context: Boolean(isVisualFollowUp && lastVisualContextRef.current),
            },
          })
        }

        const agentQuery = instruction
          ? `${visualQuery.trim()}\n\n${instruction}`
          : applyTextAgentInstruction(visualQuery)
        const rawContext = await buildContext(agentQuery)
        const contextText = [
          formatContext(rawContext),
          isVisualFollowUp ? buildVisualContext(lastVisualContextRef.current) : undefined,
        ].filter(Boolean).join('\n\n')

        const result = await multimodalApi.chat({
          query: agentQuery,
          context: contextText || undefined,
          mode: 'chat',
          file: visualFile,
          force_engine: agentOptions?.vision?.engine && agentOptions.vision.engine !== 'auto'
            ? agentOptions.vision.engine
            : undefined,
        })

        const content = await formatMultimodalResponse(result)
        logChatAgentEvent({
          surface: 'notebook_chat',
          agent: isVisualFile(visualFile) ? 'multimodal' : 'notebook_chat',
          event: 'tool_call',
          status: 'success',
          context: agentContext,
          duration_ms: Math.round(performance.now() - startedAt),
          file: fileMetadata(visualFile),
          details: {
            route: result.route,
            engine: result.engine,
            text_instruction: Boolean(instruction),
            has_image_result: Boolean(result.image_base64),
            has_video_result: Boolean(result.video_base64),
          },
        })
        if (isVisualFile(visualFile)) {
          lastVisualFileRef.current = visualFile
          lastVisualQueryRef.current = visualQuery
          lastVisualContextRef.current = content
        }
        const aiMessage: NotebookChatMessage = {
          id: `ai-${Date.now()}`,
          type: 'ai',
          content,
          timestamp: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, aiMessage])
      } catch (err: unknown) {
        const error = err as { response?: { data?: { detail?: string } }; message?: string }
        console.error('Multimodal chat error:', error)
        const messageText =
          error.response?.data?.detail || error.message || 'Failed to send message'
        toast.error(messageText)
        const aiMessage: NotebookChatMessage = {
          id: `ai-error-${Date.now()}`,
          type: 'ai',
          content: `Não consegui analisar o pedido. Detalhe técnico: ${messageText}`,
          timestamp: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, aiMessage])
      } finally {
        setIsSending(false)
      }
    },
    [buildContext, messages, notebookId, queryClient],
  )

  const clearMessages = useCallback(() => {
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(storageKeyForNotebook(notebookId))
    }
    setMessages([])
  }, [notebookId])

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
