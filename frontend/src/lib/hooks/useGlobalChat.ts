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
  GlobalChatDocument,
  GlobalChatSession,
} from '@/lib/types/api'
import {
  formatDeepResearchCompletion,
  formatDeepResearchFailure,
  formatDeepResearchProgress,
  formatDeepResearchReport,
  parseResearchJobId,
  pollDeepResearchJob,
  reconcileDeepResearchMessages,
  reportMessageId,
  reviseResearchReportMessage,
  runDeepResearchAgent,
  runDeepResearchReportEdit,
  withResolvedModelName,
} from '@/lib/chat-agents/deep-research-agent'
import { runGlobalSaveNoteAgent } from '@/lib/chat-agents/save-note-agent'
import { runRouteAgent } from '@/lib/chat-agents/route-agent'
import { runTranscriptionAgent } from '@/lib/chat-agents/transcription-agent'
import { runGraphAgent, isGraphRequest } from '@/lib/chat-agents/graph-agent'
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
import { promptLanguageLabel } from '@/lib/utils/prompt-language'
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
  // Only match visual-specific keywords — generic "again" words ("again", "de novo",
  // "outra vez") are deliberately excluded: they apply to any domain and caused
  // non-visual follow-ups (e.g. table questions) to incorrectly reuse the last photo.
  return /\b(image|picture|photo|foto|imagem|video|frame|ocr|texto|text|ler|read|extrair|extract|transcrever|transcribe|detetar|detectar|detect|identifica|identificar|identify|conta|contar|count|segment|segmenta|segmentar|sam-?3|rf-?\s?detr|rfdetr|anexo|ficheiro|anterior|anteriores|previous|before|last photo|last image|foto anterior|imagem anterior|foto de antes|imagem de antes)\b/.test(text)
}

// Specifically detects explicit "give me the previous photo/image" intent, so we
// can show a helpful message when no file is stored in memory.
function looksLikePreviousPhotoRequest(message: string): boolean {
  const text = normaliseForMatching(message)
  return /\b(foto anterior|imagem anterior|foto de antes|imagem de antes|previous photo|previous image|last photo|last image|ultima foto|ultima imagem|a foto de ha pouco|a imagem de ha pouco|que enviaste antes|que enviei antes)\b/.test(text)
}

function looksLikeDataFollowUp(message: string): boolean {
  const text = normaliseForMatching(message)
  return /\b(coluna|colunas|column|columns|linha|linhas|row|rows|valor|valores|value|values|dados|data|celula|celulas|cell|cells|campo|campos|field|fields|tabela|table|filtrar|filter|ordenar|sort|media|mean|min|max|soma|sum|contagem|count|unique|unicos|missing|nulos|null|outlier)\b/.test(text)
}

function buildVisualContext(previousResponse: string): string | undefined {
  if (!previousResponse.trim()) return undefined
  return `Última análise visual:\n${previousResponse.trim()}`
}

function messagesContainVisualExchange(messages: NotebookChatMessage[]): boolean {
  return messages.some((message) => {
    if (message.attachments?.some(a => a.kind === 'image' || a.kind === 'video')) return true
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

// Merge newly-referenced documents into the running list for a conversation,
// deduping by name: pages are unioned (sorted) and chunk counts kept at the max
// seen, so the badge reflects everything used across the whole chat.
function mergeSessionDocuments(
  existing: GlobalChatDocument[],
  incoming: GlobalChatDocument[] | undefined,
): GlobalChatDocument[] {
  if (!incoming || incoming.length === 0) return existing
  const byName = new Map<string, GlobalChatDocument>()
  for (const doc of existing) byName.set(doc.name, doc)
  for (const doc of incoming) {
    const prev = byName.get(doc.name)
    if (!prev) {
      byName.set(doc.name, { ...doc, pages: [...(doc.pages ?? [])] })
      continue
    }
    const pages = Array.from(new Set([...(prev.pages ?? []), ...(doc.pages ?? [])]))
      .sort((a, b) => a - b)
    byName.set(doc.name, {
      ...prev,
      pages,
      chunks: Math.max(prev.chunks ?? 0, doc.chunks ?? 0),
    })
  }
  return Array.from(byName.values())
}

export function useGlobalChat() {
  const { t, language } = useTranslation()
  const queryClient = useQueryClient()
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<NotebookChatMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [isVisualModelLocked, setIsVisualModelLocked] = useState(false)
  const [pendingModelOverride, setPendingModelOverride] = useState<string | null>(null)
  const [contextStats, setContextStats] = useState<GlobalChatContextStats | null>(null)
  // Every document referenced so far in the current conversation (accumulated
  // across messages), not just those used for the most recent answer. Reset
  // whenever we switch to / start a different conversation.
  const [sessionDocuments, setSessionDocuments] = useState<GlobalChatDocument[]>([])
  // Private/"temporary" chat: the next auto-created session is flagged private so
  // it never shows up in the history sidebar.
  const [privateMode, setPrivateMode] = useState(false)
  // Whether auto-select-most-recent has already run. After the user
  // explicitly deletes the active session we keep the conversation cleared
  // and do NOT pick another session for them.
  const autoSelectedRef = useRef(false)
  const hasLocalMultimodalMessagesRef = useRef(false)
  const localMessagesDirtyRef = useRef(false)
  const lastVisualFileRef = useRef<File | null>(null)
  const lastVisualQueryRef = useRef('')
  const lastVisualContextRef = useRef('')
  const lastDataFileRef = useRef<File | null>(null)
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
      appendMessage: (msg) => {
        if (currentSessionIdRef.current !== sessionId) return
        localMessagesDirtyRef.current = true
        setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg])
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
    mutationFn: (data: { title?: string; model_override?: string; private?: boolean }) =>
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
    // Optimistic delete: remove the session from the UI instantly and fire the
    // request in the background. If the server rejects it, we roll back and the
    // session reappears with an error toast.
    onMutate: async (deletedId: string) => {
      await queryClient.cancelQueries({ queryKey: QUERY_KEYS.globalChatSessions })
      const previousSessions = queryClient.getQueryData<GlobalChatSession[]>(
        QUERY_KEYS.globalChatSessions,
      )
      // Remove from the sidebar list immediately.
      queryClient.setQueryData<GlobalChatSession[]>(
        QUERY_KEYS.globalChatSessions,
        (old) => (Array.isArray(old) ? old.filter((s) => s.id !== deletedId) : old),
      )
      // If the deleted session was open, clear the panel immediately too.
      const wasActive = currentSessionId === deletedId
      if (wasActive) {
        autoSelectedRef.current = true
        hasLocalMultimodalMessagesRef.current = false
        localMessagesDirtyRef.current = false
        lastVisualFileRef.current = null
        lastVisualQueryRef.current = ''
        lastVisualContextRef.current = ''
        lastDataFileRef.current = null
        setIsVisualModelLocked(false)
        setCurrentSessionId(null)
        setMessages([])
        setSessionDocuments([])
      }
      return { previousSessions, wasActive }
    },
    onError: (err: unknown, _deletedId, context) => {
      // Roll back the optimistic removal.
      if (context?.previousSessions !== undefined) {
        queryClient.setQueryData(QUERY_KEYS.globalChatSessions, context.previousSessions)
      }
      const error = err as { response?: { data?: { detail?: string } }, message?: string }
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToDeleteSession'))
    },
    onSuccess: (_, deletedId) => {
      queryClient.removeQueries({
        queryKey: QUERY_KEYS.globalChatSession(deletedId),
      })
      toast.success(t.chat.sessionDeleted)
    },
    // Reconcile with the server in the background (confirms the delete).
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSessions })
    },
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

    // Auto-create session if none exists. The session is created lazily on the
    // first message (the "New conversation" button only clears local state), so
    // we never leave behind empty sessions titled with an internal id. Start
    // with a neutral placeholder, then generate a real title in the background.
    if (!sessionId) {
      try {
        const newSession = await globalChatApi.createSession({
          title: t.chat.newChat ?? 'Nova conversa',
          model_override: pendingModelOverride ?? undefined,
          private: privateMode,
        })
        sessionId = newSession.id
        currentSessionIdRef.current = sessionId
        setCurrentSessionId(sessionId)
        setPendingModelOverride(null)
        queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.globalChatSessions
        })
        // Generate a concise title from the first message in parallel with
        // processing it — don't block the send. The title shows in the sidebar.
        if (message.trim()) {
          const createdSessionId = sessionId
          void globalChatApi.generateTitle(createdSessionId, message)
            .then(() => {
              queryClient.invalidateQueries({
                queryKey: QUERY_KEYS.globalChatSessions
              })
            })
            .catch(() => undefined)
        }
      } catch (err: unknown) {
        const error = err as { response?: { data?: { detail?: string } }, message?: string }
        toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
        return
      }
    }

    // If the user explicitly asks for a "previous photo" but we have none stored,
    // show a helpful message and bail out early rather than sending a broken request.
    if (!file && looksLikePreviousPhotoRequest(message) && !lastVisualFileRef.current) {
      toast.info('Não encontrei uma imagem anterior nesta conversa. Envia uma nova imagem para eu poder analisá-la.')
      setIsSending(false)
      return
    }

    const isVisualFollowUp = !file && isVisualFile(lastVisualFileRef.current) && looksLikeVisualFollowUp(message)
    const visualFile = file ?? (isVisualFollowUp ? lastVisualFileRef.current ?? undefined : undefined)

    // Add user message optimistically
    const userMessage: NotebookChatMessage = {
      id: `temp-${Date.now()}`,
      type: 'human',
      content: message,
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

      // Follow-up edits to an existing deep-research report rewrite that same
      // message in place instead of producing a new one.
      if (!file) {
        const reportEdit = await runDeepResearchReportEdit({
          message,
          messages,
          queryClient,
          modelId: modelOverride ?? (currentSession?.model_override ?? undefined),
          context: agentContext,
        })
        if (reportEdit) {
          localMessagesDirtyRef.current = true
          setMessages(prev => prev.map(m => m.id === reportEdit.targetMessageId ? { ...m, content: reportEdit.newContent } : m))
          void globalChatApi.persistExchange(sessionId, {
            user_message: userMessage.content,
            assistant_message: reportEdit.newContent,
            user_message_id: userMessage.id,
            assistant_message_id: reportEdit.targetMessageId,
          }).then(() => {
            queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSession(sessionId) })
            queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSessions })
          }).catch((persistError) => {
            console.error('Failed to persist report edit:', persistError)
          })
          toast.success('Relatório atualizado.')
          return
        }
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
              const completionContent = formatDeepResearchCompletion(message, deepResearchOptions!, job)
              const rptContent = formatDeepResearchReport(job)
              const rptId = reportMessageId(content.jobId)
              if (currentSessionIdRef.current === sessionId) {
                localMessagesDirtyRef.current = true
                setMessages(prev => {
                  const updated = prev.map(m => m.id === aiMessageId ? { ...m, content: completionContent } : m)
                  if (updated.some(m => m.id === rptId)) return updated
                  return [...updated, { id: rptId, type: 'ai' as const, content: rptContent, timestamp: new Date().toISOString() }]
                })
              }
              const invalidate = () => {
                queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSession(sessionId) })
                queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSessions })
              }
              void globalChatApi.persistExchange(sessionId, {
                user_message: userMessage.content,
                assistant_message: completionContent,
                user_message_id: userMessageId,
                assistant_message_id: aiMessageId,
              }).then(invalidate).catch((e) => console.error('Failed to persist DR completion:', e))
              void globalChatApi.persistExchange(sessionId, {
                user_message: userMessage.content,
                assistant_message: rptContent,
                user_message_id: userMessageId,
                assistant_message_id: rptId,
              }).then(invalidate).catch((e) => console.error('Failed to persist DR report:', e))
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

      // A table follow-up that asks for a chart ("gráfico de barras da coluna X")
      // must go to the graph agent, not the profiler — even though it mentions a
      // column. Detect chart intent up front so the profiler defers to the graph
      // block below instead of intercepting and returning a profile.
      const wantsGraph = preferredAgent === 'graph_generator' || isGraphRequest(message)

      // Data profiler: runs when a file is attached OR when the user is asking
      // a follow-up question about a table from a previous turn (re-uses the
      // stored last data file so the model sees the actual column values).
      const isDataFollowUp =
        !file && !!lastDataFileRef.current && looksLikeDataFollowUp(message) && !wantsGraph
      const dataFile = file ?? (isDataFollowUp ? lastDataFileRef.current ?? undefined : undefined)
      if (dataFile) {
        const content = await runDataProfilerAgent(
          message,
          dataFile,
          agentContext,
          preferredAgent === 'data_profiler' || isDataFollowUp,
        )
        if (content) {
          // Remember the file for future follow-ups.
          if (file) lastDataFileRef.current = file
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
        // Graph agent: reuses last data file on follow-up questions, just like
        // the data profiler block above. Triggers when the follow-up references
        // the table (column words) OR explicitly asks for a chart.
        const isGraphFollowUp =
          !file && !!lastDataFileRef.current && (looksLikeDataFollowUp(message) || wantsGraph)
        const graphFile = file ?? (isGraphFollowUp ? lastDataFileRef.current ?? undefined : undefined)
        const content = await runGraphAgent(
          message,
          graphFile,
          agentContext,
          preferredAgent === 'graph_generator' || isGraphFollowUp,
        )
        if (content) {
          if (file) lastDataFileRef.current = file
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
          // UI panel takes precedence; router parameter is the fallback so
          // phrases like "usa o sam3" actually reach the correct engine.
          force_engine: (() => {
            if (agentOptions?.vision?.engine && agentOptions.vision.engine !== 'auto') {
              return agentOptions.vision.engine
            }
            const fromRouter = routerDecision?.parameters?.force_engine
            if (fromRouter === 'sam3' || fromRouter === 'rfdetr') return fromRouter
            return undefined
          })(),
          surface: agentContext.surface,
          run_id: agentContext.runId,
          session_id: agentContext.sessionId,
          model_id: agentContext.modelId,
          language,
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
        app_language: promptLanguageLabel(language),
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
              if (data.data) {
                setContextStats(data.data)
                setSessionDocuments(prev => mergeSessionDocuments(prev, data.data.documents))
              }
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
          // Preserve ephemeral blob attachments — they are never persisted to
          // the server. Use the functional form so `prev` reflects the current
          // state (including the optimistic user message with its attachment),
          // not the stale closure value of `messages`.
          setMessages((prev) => serverMessages.map((serverMsg, i) => {
            const localMsg = prev[i]
            return localMsg?.attachments?.length
              ? { ...serverMsg, attachments: localMsg.attachments }
              : serverMsg
          }))
          setIsVisualModelLocked(messagesContainVisualExchange(serverMessages))
        }
      }).catch(() => undefined)
    }
  }, [currentSessionId, currentSession, pendingModelOverride, privateMode, refetchCurrentSession, queryClient, t, messages])

  // Switch session — opening a saved conversation always leaves private mode.
  const switchSession = useCallback((sessionId: string) => {
    hasLocalMultimodalMessagesRef.current = false
    localMessagesDirtyRef.current = false
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''
    setIsVisualModelLocked(false)
    setPrivateMode(false)
    setCurrentSessionId(sessionId)
    setContextStats(null)
    setSessionDocuments([])
  }, [])

  // Create session — an explicit "New chat" is always a normal (listed) session.
  const createSession = useCallback((title?: string) => {
    hasLocalMultimodalMessagesRef.current = false
    localMessagesDirtyRef.current = false
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''
    setIsVisualModelLocked(false)
    setPrivateMode(false)
    return createSessionMutation.mutate({ title, private: false })
  }, [createSessionMutation])

  // Start a brand-new, empty conversation WITHOUT persisting anything. The
  // actual session is created lazily on the first message (see sendMessage), so
  // repeatedly clicking "New conversation" never spawns empty/internal-id rows.
  const newConversation = useCallback(() => {
    hasLocalMultimodalMessagesRef.current = false
    localMessagesDirtyRef.current = false
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''
    lastDataFileRef.current = null
    // Keep auto-select from re-picking the most recent session for the user.
    autoSelectedRef.current = true
    setIsVisualModelLocked(false)
    setPendingModelOverride(null)
    currentSessionIdRef.current = null
    setCurrentSessionId(null)
    setMessages([])
    setContextStats(null)
    setSessionDocuments([])
  }, [])

  // Toggle private/"temporary" mode. Either direction starts a fresh, empty
  // conversation; the private session itself is created lazily on first send.
  const togglePrivateChat = useCallback(() => {
    hasLocalMultimodalMessagesRef.current = false
    localMessagesDirtyRef.current = false
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''
    setIsVisualModelLocked(false)
    setContextStats(null)
    setCurrentSessionId(null)
    setMessages([])
    // Don't auto-jump back to the most recent history session afterwards.
    autoSelectedRef.current = true
    setPrivateMode(prev => !prev)
  }, [])

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

  // Inline edit of a specific deep-research report message — updates that same
  // message in place (no new user/assistant message), mirroring the
  // chat-command edit flow.
  const reviseReport = useCallback(async (messageId: string, instruction: string) => {
    const sessionId = currentSessionId
    if (!sessionId) return
    const index = messages.findIndex(m => m.id === messageId)
    const target = index >= 0 ? messages[index] : undefined
    if (!target) return
    const result = await reviseResearchReportMessage({
      target,
      instruction,
      queryClient,
      modelId: currentSession?.model_override ?? undefined,
      context: { surface: 'global_chat', runId: createChatAgentRunId('global_chat'), sessionId },
    })
    if (!result) {
      toast.error('Não consegui atualizar o relatório.')
      return
    }
    localMessagesDirtyRef.current = true
    setMessages(prev => prev.map(m => m.id === result.targetMessageId ? { ...m, content: result.newContent } : m))
    // Re-persist the original paired human (no-op upsert by id) + the updated
    // report (same id) so nothing new is appended. Walk backwards past any AI
    // messages (e.g. the completion-notification) to find the human request.
    let pairedHuman: (typeof messages)[0] | undefined
    for (let i = index - 1; i >= 0; i--) {
      if (messages[i].type === 'human') { pairedHuman = messages[i]; break }
    }
    if (!pairedHuman) return  // no human to pair with — skip persist to avoid blank message
    void globalChatApi.persistExchange(sessionId, {
      user_message: pairedHuman.content,
      assistant_message: result.newContent,
      user_message_id: pairedHuman.id,
      assistant_message_id: result.targetMessageId,
    }).then(() => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSession(sessionId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.globalChatSessions })
    }).catch((persistError) => {
      console.error('Failed to persist inline report edit:', persistError)
    })
    toast.success('Relatório atualizado.')
  }, [messages, currentSessionId, currentSession, queryClient])

  const isDeepResearchSession = messages.some(m => parseResearchJobId(m.id) !== null)

  return {
    sessions,
    currentSession: currentSession || sessions.find(s => s.id === currentSessionId),
    currentSessionId,
    messages,
    isSending,
    isVisualModelLocked,
    isDeepResearchSession,
    loadingSessions,
    pendingModelOverride,
    contextStats,
    sessionDocuments,
    privateMode,

    createSession,
    newConversation,
    updateSession,
    deleteSession,
    switchSession,
    sendMessage,
    reviseReport,
    setModelOverride,
    togglePrivateChat,
    refetchSessions
  }
}
