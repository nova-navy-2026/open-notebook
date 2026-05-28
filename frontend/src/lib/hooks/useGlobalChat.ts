'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { useTranslation } from '@/lib/hooks/use-translation'
import { globalChatApi } from '@/lib/api/global-chat'
import { multimodalApi, type MultimodalResponse } from '@/lib/api/multimodal'
import { QUERY_KEYS } from '@/lib/api/query-client'
import {
  NotebookChatMessage,
  UpdateGlobalChatSessionRequest,
  GlobalChatContextStats,
} from '@/lib/types/api'

function createAttachment(file?: File): NotebookChatMessage['attachments'] {
  if (!file) return undefined
  const kind = file.type.startsWith('image/')
    ? 'image'
    : file.type.startsWith('video/')
      ? 'video'
      : 'file'
  return [{ name: file.name, url: URL.createObjectURL(file), kind }]
}

function isVisualFile(file?: File | null): file is File {
  return !!file && (file.type.startsWith('image/') || file.type.startsWith('video/'))
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

function looksLikeVisualToolRequest(message: string): boolean {
  const text = normaliseForMatching(message)
  return /\b(ocr|texto|text|ler|read|extrair|extract|transcrever|transcribe|detetar|detectar|detect|deteccao|identifica|identificar|identify|conta|contar|count|quantos|numero|number|how many|segment|segmenta|segmentar|localiza|localizar|locate|track|seguir|rastrear|sam-?3|rf-?\s?detr|rfdetr)\b/.test(text)
}

function looksLikeOcrRequest(message: string): boolean {
  const text = normaliseForMatching(message)
  return /\b(ocr|texto|text|ler|read|extrair|extract|transcrever|transcribe|reconhecer|recognize)\b/.test(text)
}

function buildVisualFollowUpQuery(message: string, previousQuery: string): string {
  if (!previousQuery.trim()) return message
  return `Pedido visual anterior:\n${previousQuery.trim()}\n\nPedido atual:\n${message}`
}

function buildVisualContext(previousResponse: string): string | undefined {
  if (!previousResponse.trim()) return undefined
  return `Última análise visual:\n${previousResponse.trim()}`
}

function messagesContainVisualExchange(messages: NotebookChatMessage[]): boolean {
  return messages.some((message) => {
    const content = normaliseForMatching(message.content)
    return (
      content.includes('[anexo:')
      || content.includes('resultado da analise visual')
      || content.includes('video anotado')
      || content.includes('gemma multimodal')
      || content.includes('deteccao visual')
    )
  })
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

export function useGlobalChat() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<NotebookChatMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [isVisualModelLocked, setIsVisualModelLocked] = useState(false)
  const [pendingModelOverride, setPendingModelOverride] = useState<string | null>(null)
  const [contextStats, setContextStats] = useState<GlobalChatContextStats | null>(null)
  // Whether auto-select-most-recent has already run. After the user
  // explicitly deletes the active session we keep the conversation cleared
  // and do NOT pick another session for them.
  const autoSelectedRef = useRef(false)
  const hasLocalMultimodalMessagesRef = useRef(false)
  const lastVisualFileRef = useRef<File | null>(null)
  const lastVisualQueryRef = useRef('')
  const lastVisualContextRef = useRef('')

  // Fetch all global chat sessions
  const {
    data: sessions = [],
    isLoading: loadingSessions,
    refetch: refetchSessions
  } = useQuery({
    queryKey: QUERY_KEYS.globalChatSessions,
    queryFn: () => globalChatApi.listSessions(),
  })

  // Fetch current session with messages
  const {
    data: currentSession,
    refetch: refetchCurrentSession
  } = useQuery({
    queryKey: QUERY_KEYS.globalChatSession(currentSessionId!),
    queryFn: () => globalChatApi.getSession(currentSessionId!),
    enabled: !!currentSessionId
  })

  // Update messages when current session changes.
  // Skip while a message is being sent so that the optimistic user message
  // isn't wiped out by a stale fetch of the freshly-created session.
  useEffect(() => {
    if (currentSession?.messages && !isSending && !hasLocalMultimodalMessagesRef.current) {
      setMessages(currentSession.messages)
      setIsVisualModelLocked(messagesContainVisualExchange(currentSession.messages))
    }
  }, [currentSession, isSending])

  // Auto-select most recent session — only on the very first load.
  useEffect(() => {
    if (!autoSelectedRef.current && sessions.length > 0 && !currentSessionId) {
      autoSelectedRef.current = true
      setCurrentSessionId(sessions[0].id)
    }
  }, [sessions, currentSessionId])

  // Create session mutation
  const createSessionMutation = useMutation({
    mutationFn: (data: { title?: string; model_override?: string }) =>
      globalChatApi.createSession(data),
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.globalChatSessions
      })
      setCurrentSessionId(newSession.id)
      toast.success(t.chat.sessionCreated)
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string }
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
    }
  })

  // Update session mutation
  const updateSessionMutation = useMutation({
    mutationFn: ({ sessionId, data }: {
      sessionId: string
      data: UpdateGlobalChatSessionRequest
    }) => globalChatApi.updateSession(sessionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.globalChatSessions
      })
      if (currentSessionId) {
        queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.globalChatSession(currentSessionId)
        })
      }
      toast.success(t.chat.sessionUpdated)
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string }
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToUpdateSession'))
    }
  })

  // Delete session mutation
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) =>
      globalChatApi.deleteSession(sessionId),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.globalChatSessions
      })
      // Drop the cached session so the messages effect can't repopulate
      // from stale data after we clear it below.
      queryClient.removeQueries({
        queryKey: QUERY_KEYS.globalChatSession(deletedId)
      })
      if (currentSessionId === deletedId) {
        // Mark auto-select as already done so we don't immediately
        // jump into another session — the user wants the panel cleared.
        autoSelectedRef.current = true
        hasLocalMultimodalMessagesRef.current = false
        lastVisualFileRef.current = null
        lastVisualQueryRef.current = ''
        lastVisualContextRef.current = ''
        setIsVisualModelLocked(false)
        setCurrentSessionId(null)
        setMessages([])
      }
      toast.success(t.chat.sessionDeleted)
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string }
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToDeleteSession'))
    }
  })

  // Send message
  const sendMessage = useCallback(async (message: string, modelOverride?: string, file?: File) => {
    let sessionId = currentSessionId

    // Auto-create session if none exists
    if (!sessionId) {
      try {
        const defaultTitle = message.length > 30
          ? `${message.substring(0, 30)}...`
          : message
        const newSession = await globalChatApi.createSession({
          title: defaultTitle,
          model_override: pendingModelOverride ?? undefined
        })
        sessionId = newSession.id
        setCurrentSessionId(sessionId)
        setPendingModelOverride(null)
        queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.globalChatSessions
        })
      } catch (err: unknown) {
        const error = err as { response?: { data?: { detail?: string } }, message?: string }
        toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
        return
      }
    }

    const isVisualFollowUp = !file && isVisualFile(lastVisualFileRef.current) && looksLikeVisualFollowUp(message)
    const visualFile = file ?? (isVisualFollowUp ? lastVisualFileRef.current ?? undefined : undefined)

    // Add user message optimistically
    const userMessage: NotebookChatMessage = {
      id: `temp-${Date.now()}`,
      type: 'human',
      content: file ? `${message}\n\n[Anexo: ${file.name}]` : message,
      attachments: createAttachment(file),
      timestamp: new Date().toISOString()
    }
    setMessages(prev => [...prev, userMessage])
    setIsSending(true)

    try {
      if (isVisualFile(visualFile)) {
        hasLocalMultimodalMessagesRef.current = true
        setIsVisualModelLocked(true)
        const visualQuery = isVisualFollowUp
          && looksLikeVisualToolRequest(message)
          && !looksLikeOcrRequest(message)
          ? buildVisualFollowUpQuery(message, lastVisualQueryRef.current)
          : message
        const result = await multimodalApi.chat({
          query: visualQuery,
          context: isVisualFollowUp ? buildVisualContext(lastVisualContextRef.current) : undefined,
          mode: 'chat',
          file: visualFile,
        })
        const content = await formatMultimodalResponse(result)
        lastVisualFileRef.current = visualFile
        lastVisualQueryRef.current = visualQuery
        lastVisualContextRef.current = content
        const aiMessage: NotebookChatMessage = {
          id: `ai-${Date.now()}`,
          type: 'ai',
          content,
          timestamp: new Date().toISOString()
        }
        setMessages(prev => [...prev, aiMessage])
        void globalChatApi.persistExchange(sessionId, {
          user_message: userMessage.content,
          assistant_message: content,
        }).then(() => {
          queryClient.invalidateQueries({
            queryKey: QUERY_KEYS.globalChatSessions
          })
          queryClient.invalidateQueries({
            queryKey: QUERY_KEYS.globalChatSession(sessionId)
          })
        }).catch((persistError) => {
          console.error('Failed to persist multimodal exchange:', persistError)
          toast.error('A resposta foi gerada, mas não consegui guardar esta troca na conversa.')
        })
        return
      }

      const body = await globalChatApi.sendMessageStream({
        session_id: sessionId,
        message,
        model_override: modelOverride ?? (currentSession?.model_override ?? undefined)
      })

      if (!body) throw new Error('No response body')

      const reader = body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let aiMessageId: string | null = null
      let aiContent = ''

      const ensureAiMessage = () => {
        if (!aiMessageId) {
          aiMessageId = `ai-${Date.now()}`
          const initial: NotebookChatMessage = {
            id: aiMessageId,
            type: 'ai',
            content: '',
            timestamp: new Date().toISOString()
          }
          setMessages(prev => [...prev, initial])
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() ?? ''
        for (const evt of events) {
          const line = evt.split('\n').find(l => l.startsWith('data: '))
          if (!line) continue
          try {
            const data = JSON.parse(line.slice(6))
            if (data.type === 'delta') {
              ensureAiMessage()
              aiContent += data.content || ''
              setMessages(prev =>
                prev.map(m => m.id === aiMessageId ? { ...m, content: aiContent } : m)
              )
            } else if (data.type === 'complete') {
              ensureAiMessage()
              aiContent = data.content || aiContent
              setMessages(prev =>
                prev.map(m => m.id === aiMessageId ? { ...m, content: aiContent } : m)
              )
            } else if (data.type === 'context_stats') {
              if (data.data) setContextStats(data.data)
            } else if (data.type === 'error') {
              throw new Error(data.message || 'Stream error')
            }
          } catch (e) {
            if (!(e instanceof SyntaxError)) throw e
          }
        }
      }

      await refetchCurrentSession()
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }, message?: string }
      console.error('Error sending message:', error)
      const rawMessage = error.response?.data?.detail || error.message
      const messageText = getApiErrorMessage(
        rawMessage,
        (key) => t(key),
        'apiErrors.failedToSendMessage'
      )
      toast.error(messageText)
      const aiMessage: NotebookChatMessage = {
        id: `ai-error-${Date.now()}`,
        type: 'ai',
        content: `Não consegui analisar o pedido. Detalhe técnico: ${messageText}`,
        timestamp: new Date().toISOString()
      }
      setMessages(prev => [...prev, aiMessage])
    } finally {
      setIsSending(false)
    }
  }, [currentSessionId, currentSession, pendingModelOverride, refetchCurrentSession, queryClient, t])

  // Switch session
  const switchSession = useCallback((sessionId: string) => {
    hasLocalMultimodalMessagesRef.current = false
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''
    setIsVisualModelLocked(false)
    setCurrentSessionId(sessionId)
    setContextStats(null)
  }, [])

  // Create session
  const createSession = useCallback((title?: string) => {
    hasLocalMultimodalMessagesRef.current = false
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''
    setIsVisualModelLocked(false)
    return createSessionMutation.mutate({ title })
  }, [createSessionMutation])

  // Update session
  const updateSession = useCallback((sessionId: string, data: UpdateGlobalChatSessionRequest) => {
    return updateSessionMutation.mutate({ sessionId, data })
  }, [updateSessionMutation])

  // Delete session
  const deleteSession = useCallback((sessionId: string) => {
    return deleteSessionMutation.mutate(sessionId)
  }, [deleteSessionMutation])

  // Set model override
  const setModelOverride = useCallback((model: string | null) => {
    if (currentSessionId) {
      updateSessionMutation.mutate({
        sessionId: currentSessionId,
        data: { model_override: model }
      })
    } else {
      setPendingModelOverride(model)
    }
  }, [currentSessionId, updateSessionMutation])

  return {
    sessions,
    currentSession: currentSession || sessions.find(s => s.id === currentSessionId),
    currentSessionId,
    messages,
    isSending,
    isVisualModelLocked,
    loadingSessions,
    pendingModelOverride,
    contextStats,

    createSession,
    updateSession,
    deleteSession,
    switchSession,
    sendMessage,
    setModelOverride,
    refetchSessions
  }
}
