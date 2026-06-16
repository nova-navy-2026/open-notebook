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
import {
  formatDeepResearchFailure,
  formatDeepResearchProgress,
  formatDeepResearchResult,
  pollDeepResearchJob,
  reconcileDeepResearchMessages,
  runDeepResearchAgent,
  withResolvedModelName,
} from '@/lib/chat-agents/deep-research-agent'
import { runGlobalSaveNoteAgent } from '@/lib/chat-agents/save-note-agent'
import { runRouteAgent } from '@/lib/chat-agents/route-agent'
import { runTranscriptionAgent } from '@/lib/chat-agents/transcription-agent'
import { runGraphAgent } from '@/lib/chat-agents/graph-agent'
import { runDataProfilerAgent } from '@/lib/chat-agents/data-profiler-agent'
import {
  createChatAgentRunId,
  fileMetadata,
  logChatAgentEvent,
  previewMessage,
} from '@/lib/chat-agents/logger'
import { routeChatAgentWithGemma } from '@/lib/chat-agents/router'
import {
  detectTextAgentInstruction,
  instructionForVisualMode,
} from '@/lib/utils/chat-agents'
import { getAttachmentKind, isVisualLikeFile } from '@/lib/utils/file-kind'
import type { ChatAgentUiOptions, ChatDeepResearchOptions } from '@/lib/utils/chat-agents'

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
  const localMessagesDirtyRef = useRef(false)
  const lastVisualFileRef = useRef<File | null>(null)
  const lastVisualQueryRef = useRef('')
  const lastVisualContextRef = useRef('')
  const currentSessionIdRef = useRef<string | null>(currentSessionId)
  // Deep research jobs already being polled by this hook instance (inline or
  // reconciled), so the reconciler never double-polls the same job.
  const polledResearchJobsRef = useRef<Set<string>>(new Set())

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
      if (localMessagesDirtyRef.current && currentSession.messages.length < messages.length) {
        return
      }
      localMessagesDirtyRef.current = false
      setMessages(currentSession.messages)
      setIsVisualModelLocked(messagesContainVisualExchange(currentSession.messages))
    }
  }, [currentSession, isSending, messages.length])

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId
  }, [currentSessionId])

  // Resume any deep research jobs whose "em curso" message was loaded from the
  // server (e.g. after a reload or navigating away and back). Without this the
  // message would stay frozen on the progress placeholder forever.
  useEffect(() => {
    const sessionId = currentSessionId
    if (!sessionId) return
    reconcileDeepResearchMessages({
      messages,
      polledJobs: polledResearchJobsRef.current,
      queryClient,
      isActive: () => currentSessionIdRef.current === sessionId,
      applyContent: (id, content) => {
        if (currentSessionIdRef.current !== sessionId) return
        localMessagesDirtyRef.current = true
        setMessages(prev => prev.map(m => m.id === id ? { ...m, content } : m))
      },
      persist: ({ userMessage, userMessageId, assistantMessage, assistantMessageId }) => {
        void globalChatApi.persistExchange(sessionId, {
          user_message: userMessage,
          assistant_message: assistantMessage,
          user_message_id: userMessageId,
          assistant_message_id: assistantMessageId,
        }).then(() => {
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSession(sessionId) })
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSessions })
        }).catch((persistError) => {
          console.error('Failed to persist reconciled deep research exchange:', persistError)
        })
      },
    })
  }, [messages, currentSessionId, queryClient])

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
        localMessagesDirtyRef.current = false
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
  const sendMessage = useCallback(async (
    message: string,
    modelOverride?: string,
    file?: File,
    deepResearch?: ChatDeepResearchOptions,
    agentOptions?: ChatAgentUiOptions,
  ) => {
    let sessionId = currentSessionId
    let activeTextAgentContext: {
      instruction?: string
      name?: string
      startedAt?: number
      runId?: string
    } = {}

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
        currentSessionIdRef.current = sessionId
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
      content: file
        ? `${message}\n\n[Anexo: ${file.name}]`
        : isVisualFollowUp && visualFile
          ? `${message}\n\n[Imagem anterior: ${visualFile.name}]`
          : message,
      attachments: createAttachment(file ?? (isVisualFollowUp ? visualFile : undefined)),
      timestamp: new Date().toISOString()
    }
    setMessages(prev => [...prev, userMessage])
    localMessagesDirtyRef.current = true
    setIsSending(true)

    try {
      const agentContext = {
        surface: 'global_chat' as const,
        runId: createChatAgentRunId('global_chat'),
        sessionId,
        modelId: modelOverride ?? (currentSession?.model_override ?? undefined),
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
      const deepResearchOptions = withResolvedModelName(
        deepResearch ?? (preferredAgent === 'deep_research'
          ? { reportType: 'research_report', tone: 'Objective' }
          : undefined),
        queryClient,
      )

      if (!file) {
        const content = await runDeepResearchAgent({
          message,
          options: deepResearchOptions,
          queryClient,
          context: agentContext,
        })
        if (content) {
          const aiMessageId = `ai-research-${content.jobId}`
          const userMessageId = userMessage.id
          const aiMessage: NotebookChatMessage = {
            id: aiMessageId,
            type: 'ai',
            content: content.initialContent,
            timestamp: new Date().toISOString()
          }
          setMessages(prev => [...prev, aiMessage])
          // Claim this job so the reconciler effect won't start a second poll.
          polledResearchJobsRef.current.add(content.jobId)
          void globalChatApi.persistExchange(sessionId, {
            user_message: userMessage.content,
            assistant_message: content.initialContent,
            user_message_id: userMessageId,
            assistant_message_id: aiMessageId,
          }).then(() => {
            queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSession(sessionId) })
            queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSessions })
          }).catch((persistError) => {
            console.error('Failed to persist initial deep research exchange:', persistError)
          })
          void pollDeepResearchJob({
            jobId: content.jobId,
            queryClient,
            onUpdate: (_content, job) => {
              if (currentSessionIdRef.current !== sessionId) return
              const nextContent = formatDeepResearchProgress(message, deepResearchOptions!, content.jobId, job)
              setMessages(prev => prev.map(m => m.id === aiMessageId ? { ...m, content: nextContent } : m))
            },
            onComplete: (_content, job) => {
              const finalContent = formatDeepResearchResult(message, deepResearchOptions!, job)
              if (currentSessionIdRef.current === sessionId) {
                localMessagesDirtyRef.current = true
                setMessages(prev => prev.map(m => m.id === aiMessageId ? { ...m, content: finalContent } : m))
              }
              void globalChatApi.persistExchange(sessionId, {
                user_message: userMessage.content,
                assistant_message: finalContent,
                user_message_id: userMessageId,
                assistant_message_id: aiMessageId,
              }).then(() => {
                queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSession(sessionId) })
                queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSessions })
              }).catch((persistError) => {
                console.error('Failed to persist deep research exchange:', persistError)
              })
            },
            onFailure: (_content, job) => {
              const failureContent = formatDeepResearchFailure(
                message,
                deepResearchOptions!,
                content.jobId,
                job?.error ?? (typeof _content === 'string' ? _content : undefined),
              )
              if (currentSessionIdRef.current === sessionId) {
                localMessagesDirtyRef.current = true
                setMessages(prev => prev.map(m => m.id === aiMessageId ? { ...m, content: failureContent } : m))
              }
              void globalChatApi.persistExchange(sessionId, {
                user_message: userMessage.content,
                assistant_message: failureContent,
                user_message_id: userMessageId,
                assistant_message_id: aiMessageId,
              }).catch((persistError) => {
                console.error('Failed to persist failed deep research exchange:', persistError)
              })
            },
          }).catch((pollError) => {
            console.error('Failed to poll deep research job:', pollError)
          })
          return
        }
      }

      if (!file) {
        const content = await runGlobalSaveNoteAgent({
          message,
          messages,
          queryClient,
          context: agentContext,
          force: preferredAgent === 'save_note',
          targetNotebookId: agentOptions?.saveNote?.notebookId,
        })
        if (content) {
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
          }).catch((persistError) => {
            console.error('Failed to persist save-note exchange:', persistError)
          })
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
            timestamp: new Date().toISOString()
          }
          setMessages(prev => [...prev, aiMessage])
          void globalChatApi.persistExchange(sessionId, {
            user_message: userMessage.content,
            assistant_message: content,
          }).catch((persistError) => {
            console.error('Failed to persist route exchange:', persistError)
          })
          return
        }
      }

      if (file) {
        const content = await runDataProfilerAgent(
          message,
          file,
          agentContext,
          preferredAgent === 'data_profiler',
        )
        if (content) {
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
          }).catch((persistError) => {
            console.error('Failed to persist data profile exchange:', persistError)
          })
          return
        }
      }

      {
        const content = await runGraphAgent(
          message,
          file,
          agentContext,
          preferredAgent === 'graph_generator',
        )
        if (content) {
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
          }).catch((persistError) => {
            console.error('Failed to persist graph exchange:', persistError)
          })
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
            timestamp: new Date().toISOString()
          }
          setMessages(prev => [...prev, aiMessage])
          void globalChatApi.persistExchange(sessionId, {
            user_message: userMessage.content,
            assistant_message: content,
          }).catch((persistError) => {
            console.error('Failed to persist transcription exchange:', persistError)
          })
          return
        }
      }

      if (isVisualFile(visualFile)) {
        const startedAt = performance.now()
        hasLocalMultimodalMessagesRef.current = true
        setIsVisualModelLocked(true)
        const visualModeInstruction = instructionForVisualMode(agentOptions?.vision?.mode)
        const visualQuery = visualModeInstruction
          ? `${message.trim()}\n\n${visualModeInstruction}`
          : message
        logChatAgentEvent({
          surface: 'global_chat',
          agent: 'multimodal',
          event: 'selected',
          status: 'selected',
          context: agentContext,
          message_preview: previewMessage(message),
          file: fileMetadata(visualFile),
          details: {
            follow_up: isVisualFollowUp,
            has_context: Boolean(isVisualFollowUp && lastVisualContextRef.current),
            mode: agentOptions?.vision?.mode ?? 'auto',
          },
        })
        const result = await multimodalApi.chat({
          query: visualQuery,
          context: isVisualFollowUp ? buildVisualContext(lastVisualContextRef.current) : undefined,
          mode: 'chat',
          file: visualFile,
          force_engine: agentOptions?.vision?.engine && agentOptions.vision.engine !== 'auto'
            ? agentOptions.vision.engine
            : undefined,
          surface: agentContext.surface,
          run_id: agentContext.runId,
          session_id: agentContext.sessionId,
          model_id: agentContext.modelId,
        })
        const content = await formatMultimodalResponse(result)
        logChatAgentEvent({
          surface: 'global_chat',
          agent: 'multimodal',
          event: 'tool_call',
          status: 'success',
          context: agentContext,
          duration_ms: Math.round(performance.now() - startedAt),
          file: fileMetadata(visualFile),
          details: {
            route: result.route,
            engine: result.engine,
            has_image_result: Boolean(result.image_base64),
            has_video_result: Boolean(result.video_base64),
          },
        })
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

      const agentInstruction = routerDecision?.instruction || detectTextAgentInstruction(message)
      if (agentInstruction) {
        activeTextAgentContext = {
          instruction: agentInstruction,
          name: preferredAgent ?? 'text_instruction',
          startedAt: performance.now(),
          runId: agentContext.runId,
        }
        logChatAgentEvent({
          surface: 'global_chat',
          agent: activeTextAgentContext.name ?? 'text_instruction',
          event: 'selected',
          status: 'selected',
          context: agentContext,
          message_preview: previewMessage(message),
          details: { instruction: agentInstruction.split('\n')[0] },
        })
      }

      const body = await globalChatApi.sendMessageStream({
        session_id: sessionId,
        message,
        model_override: modelOverride ?? (currentSession?.model_override ?? undefined),
        agent_instruction: agentInstruction,
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

      if (activeTextAgentContext.instruction && activeTextAgentContext.startedAt) {
        logChatAgentEvent({
          surface: 'global_chat',
          agent: activeTextAgentContext.name ?? 'text_instruction',
          event: 'tool_call',
          status: 'success',
          context: agentContext,
          duration_ms: Math.round(performance.now() - activeTextAgentContext.startedAt),
          details: {
            response_chars: aiContent.length,
            instruction: activeTextAgentContext.instruction.split('\n')[0],
          },
        })
      }

      await refetchCurrentSession()
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }, message?: string }
      if (activeTextAgentContext.instruction && activeTextAgentContext.startedAt) {
        logChatAgentEvent({
          surface: 'global_chat',
          agent: activeTextAgentContext.name ?? 'text_instruction',
          event: 'tool_call',
          status: 'failure',
          context: {
            surface: 'global_chat',
            runId: activeTextAgentContext.runId,
            sessionId,
            modelId: modelOverride ?? (currentSession?.model_override ?? undefined),
          },
          duration_ms: Math.round(performance.now() - activeTextAgentContext.startedAt),
          details: { error: error.response?.data?.detail || error.message || String(error) },
        })
      }
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
      void refetchCurrentSession().then((result) => {
        const serverMessages = result.data?.messages
        if (serverMessages && serverMessages.length >= messages.length + 2) {
          localMessagesDirtyRef.current = false
          setMessages(serverMessages)
          setIsVisualModelLocked(messagesContainVisualExchange(serverMessages))
        }
      }).catch(() => undefined)
    }
  }, [currentSessionId, currentSession, pendingModelOverride, refetchCurrentSession, queryClient, t, messages])

  // Switch session
  const switchSession = useCallback((sessionId: string) => {
    hasLocalMultimodalMessagesRef.current = false
    localMessagesDirtyRef.current = false
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
    localMessagesDirtyRef.current = false
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
