'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { useTranslation } from '@/lib/hooks/use-translation'
import { globalChatApi } from '@/lib/api/global-chat'
import { QUERY_KEYS } from '@/lib/api/query-client'
import {
  NotebookChatMessage,
  UpdateGlobalChatSessionRequest,
  GlobalChatContextStats,
} from '@/lib/types/api'

export function useGlobalChat() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<NotebookChatMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [pendingModelOverride, setPendingModelOverride] = useState<string | null>(null)
  const [contextStats, setContextStats] = useState<GlobalChatContextStats | null>(null)
  // Whether auto-select-most-recent has already run. After the user
  // explicitly deletes the active session we keep the conversation cleared
  // and do NOT pick another session for them.
  const autoSelectedRef = useRef(false)

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

  // Update messages when current session changes
  useEffect(() => {
    if (currentSession?.messages) {
      setMessages(currentSession.messages)
    }
  }, [currentSession])

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
  const sendMessage = useCallback(async (message: string, modelOverride?: string) => {
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

    // Add user message optimistically
    const userMessage: NotebookChatMessage = {
      id: `temp-${Date.now()}`,
      type: 'human',
      content: message,
      timestamp: new Date().toISOString()
    }
    setMessages(prev => [...prev, userMessage])
    setIsSending(true)

    try {
      const response = await globalChatApi.sendMessage({
        session_id: sessionId,
        message,
        model_override: modelOverride ?? (currentSession?.model_override ?? undefined)
      })

      setMessages(response.messages)
      if (response.context_stats) {
        setContextStats(response.context_stats)
      }
      await refetchCurrentSession()
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }, message?: string }
      console.error('Error sending message:', error)
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToSendMessage'))
      setMessages(prev => prev.filter(msg => !msg.id.startsWith('temp-')))
    } finally {
      setIsSending(false)
    }
  }, [currentSessionId, currentSession, pendingModelOverride, refetchCurrentSession, queryClient, t])

  // Switch session
  const switchSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId)
    setContextStats(null)
  }, [])

  // Create session
  const createSession = useCallback((title?: string) => {
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
