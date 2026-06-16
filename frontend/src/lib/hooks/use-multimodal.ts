'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { chatApi } from '@/lib/api/chat'
import { multimodalApi } from '@/lib/api/multimodal'
import {
  SourceListResponse,
  NoteResponse,
  UpdateNotebookChatSessionRequest,
} from '@/lib/types/api'
import { ContextSelections } from '@/app/(dashboard)/notebooks/[id]/page'
import { NotebookChatMessage } from '@/lib/types/api'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import type { MultimodalResponse } from '@/lib/api/multimodal'
import {
  formatDeepResearchFailure,
  formatDeepResearchProgress,
  formatDeepResearchResult,
  pollDeepResearchJob,
  reconcileDeepResearchMessages,
  runDeepResearchAgent,
  runDeepResearchReportEdit,
  withResolvedModelName,
} from '@/lib/chat-agents/deep-research-agent'
import { runNotebookSaveNoteAgent } from '@/lib/chat-agents/save-note-agent'
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
  applyTextAgentInstruction,
  detectTextAgentInstruction,
  instructionForVisualMode,
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

function formatContext(context: {
  sources: Array<Record<string, unknown>>
  notes: Array<Record<string, unknown>>
  navy_corpus?: Array<Record<string, unknown>>
}): string {
  const parts: string[] = []

  for (const item of context.sources) {
    const title = (item.title as string) || (item.id as string) || 'Source'
    const id = (item.id as string) || ''
    const content = (
      (item.content as string) ||
      (item.full_text as string) ||
      (item.visual_content as string) ||
      (item.caption as string) ||
      (item.processing_status as string) ||
      ''
    )
    if (content.trim()) {
      parts.push(`[Source ${id} – ${title}]:\n${content}`)
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

function buildRecentChatContext(messages: NotebookChatMessage[]): string | undefined {
  const recent = messages.slice(-8)
  if (recent.length === 0) return undefined

  const transcript = recent
    .map((message) => {
      const role = message.type === 'human' ? 'Utilizador' : 'Assistente'
      return `${role}:\n${message.content.trim()}`
    })
    .join('\n\n')
    .slice(-12000)

  return transcript.trim() ? `Conversa recente:\n${transcript}` : undefined
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
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<NotebookChatMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [tokenCount, setTokenCount] = useState(0)
  const [charCount, setCharCount] = useState(0)
  const [pendingModelOverride, setPendingModelOverride] = useState<string | null>(null)
  const lastVisualFileRef = useRef<File | null>(null)
  const lastVisualQueryRef = useRef('')
  const lastVisualContextRef = useRef('')
  const notebookIdRef = useRef(notebookId)
  const autoSelectedRef = useRef(false)
  const syncedSessionRef = useRef<string | null>(null)
  // Deep research jobs already being polled by this hook instance (inline or
  // reconciled), so the reconciler never double-polls the same job.
  const polledResearchJobsRef = useRef<Set<string>>(new Set())

  const {
    data: sessions = [],
    isLoading: loadingSessions,
    refetch: refetchSessions,
  } = useQuery({
    queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
    queryFn: () => chatApi.listSessions(notebookId),
    enabled: !!notebookId,
  })

  const { data: currentSession, refetch: refetchCurrentSession } = useQuery({
    queryKey: QUERY_KEYS.notebookChatSession(currentSessionId!),
    queryFn: () => chatApi.getSession(currentSessionId!),
    enabled: !!notebookId && !!currentSessionId,
  })

  useEffect(() => {
    if (!currentSession?.id || isSending) return
    const sessionChanged = syncedSessionRef.current !== currentSession.id
    const serverMessages = currentSession.messages ?? []
    if (sessionChanged) {
      setMessages(serverMessages)
      syncedSessionRef.current = currentSession.id
      return
    }
    if (serverMessages.length > 0) {
      setMessages(serverMessages)
    }
  }, [currentSession, isSending])

  useEffect(() => {
    if (!autoSelectedRef.current && sessions.length > 0 && !currentSessionId) {
      autoSelectedRef.current = true
      setCurrentSessionId(sessions[0].id)
    }
  }, [sessions, currentSessionId])

  // Resume any deep research jobs whose "em curso" message was loaded from the
  // server (e.g. after a reload or navigating away and back), so the message
  // updates to phases/the final report instead of staying frozen.
  useEffect(() => {
    const sessionId = currentSessionId
    if (!sessionId) return
    reconcileDeepResearchMessages({
      messages,
      polledJobs: polledResearchJobsRef.current,
      queryClient,
      isActive: () => notebookIdRef.current === notebookId,
      applyContent: (id, content) => {
        if (notebookIdRef.current !== notebookId) return
        setMessages((prev) => prev.map((m) => m.id === id ? { ...m, content } : m))
      },
      persist: ({ userMessage, userMessageId, assistantMessage, assistantMessageId }) => {
        void chatApi.persistExchange(sessionId, {
          user_message: userMessage,
          assistant_message: assistantMessage,
          user_message_id: userMessageId,
          assistant_message_id: assistantMessageId,
        }).then(() => {
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId) })
        }).catch((persistError) => {
          console.error('Failed to persist reconciled notebook deep research exchange:', persistError)
        })
      },
    })
  }, [messages, currentSessionId, notebookId, queryClient])

  const createSessionMutation = useMutation({
    mutationFn: (data: { title?: string; model_override?: string | null }) =>
      chatApi.createSession({
        notebook_id: notebookId,
        title: data.title,
        model_override: data.model_override ?? undefined,
      }),
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
      setCurrentSessionId(newSession.id)
      toast.success(t.chat.sessionCreated)
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
    },
  })

  const updateSessionMutation = useMutation({
    mutationFn: ({ sessionId, data }: { sessionId: string; data: UpdateNotebookChatSessionRequest }) =>
      chatApi.updateSession(sessionId, data),
    onSuccess: (_updated, vars) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(vars.sessionId) })
      toast.success(t.chat.sessionUpdated)
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToUpdateSession'))
    },
  })

  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => chatApi.deleteSession(sessionId),
    onSuccess: (_result, deletedId) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
      queryClient.removeQueries({ queryKey: QUERY_KEYS.notebookChatSession(deletedId) })
      if (currentSessionId === deletedId) {
        autoSelectedRef.current = true
        syncedSessionRef.current = null
        setCurrentSessionId(null)
        setMessages([])
      }
      toast.success(t.chat.sessionDeleted)
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToDeleteSession'))
    },
  })

  useEffect(() => {
    notebookIdRef.current = notebookId
    lastVisualFileRef.current = null
    lastVisualQueryRef.current = ''
    lastVisualContextRef.current = ''
    autoSelectedRef.current = false
    syncedSessionRef.current = null
    setCurrentSessionId(null)
    setMessages([])
  }, [notebookId])

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
      modelOverride?: string,
      file?: File,
      deepResearch?: ChatDeepResearchOptions,
      agentOptions?: ChatAgentUiOptions,
    ) => {
      let sessionId = currentSessionId
      if (!sessionId) {
        try {
          const defaultTitle = message.length > 30 ? `${message.substring(0, 30)}...` : message
          const newSession = await chatApi.createSession({
            notebook_id: notebookId,
            title: defaultTitle,
            model_override: pendingModelOverride ?? undefined,
          })
          sessionId = newSession.id
          setCurrentSessionId(sessionId)
          setPendingModelOverride(null)
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
        } catch (err: unknown) {
          const error = err as { response?: { data?: { detail?: string } }; message?: string }
          toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
          return
        }
      }

      const isVisualFollowUp = !file && isVisualFile(lastVisualFileRef.current) && looksLikeVisualFollowUp(message)
      const visualFile = file ?? (isVisualFollowUp ? lastVisualFileRef.current ?? undefined : undefined)
      const visualModeInstruction = instructionForVisualMode(agentOptions?.vision?.mode)
      const visualQuery = visualModeInstruction
        ? `${message.trim()}\n\n${visualModeInstruction}`
        : message

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

      const agentContext = {
        surface: 'notebook_chat' as const,
        runId: createChatAgentRunId('notebook_chat'),
        notebookId,
        sessionId,
        modelId: modelOverride ?? (currentSession?.model_override ?? undefined),
      }
      const appendAndPersistAssistant = async (content: string, idPrefix = 'ai') => {
        const aiMessage: NotebookChatMessage = {
          id: `${idPrefix}-${Date.now()}`,
          type: 'ai',
          content,
          timestamp: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, aiMessage])
        try {
          await chatApi.persistExchange(sessionId!, {
            user_message: userMessage.content,
            assistant_message: content,
          })
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId!) })
        } catch (persistError) {
          console.error('Failed to persist notebook chat exchange:', persistError)
        }
      }
      let activeAgentForFailure = 'notebook_chat'
      let activeTextAgentContext: {
        name?: string
        instruction?: string
        startedAt?: number
      } = {}

      try {
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
            setMessages((prev) => prev.map((m) => m.id === reportEdit.targetMessageId ? { ...m, content: reportEdit.newContent } : m))
            void chatApi.persistExchange(sessionId!, {
              user_message: userMessage.content,
              assistant_message: reportEdit.newContent,
              user_message_id: userMessage.id,
              assistant_message_id: reportEdit.targetMessageId,
            }).then(() => {
              queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
              queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId!) })
            }).catch((persistError) => {
              console.error('Failed to persist notebook report edit:', persistError)
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
        activeAgentForFailure = preferredAgent ?? activeAgentForFailure
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
            notebookId,
            context: agentContext,
          })
        if (content) {
          const aiMessageId = `ai-research-${content.jobId}`
          const userMessageId = userMessage.id
          const aiMessage: NotebookChatMessage = {
            id: aiMessageId,
            type: 'ai',
            content: content.initialContent,
            timestamp: new Date().toISOString(),
          }
          setMessages((prev) => [...prev, aiMessage])
          // Claim this job so the reconciler effect won't start a second poll.
          polledResearchJobsRef.current.add(content.jobId)
          void chatApi.persistExchange(sessionId!, {
            user_message: userMessage.content,
            assistant_message: content.initialContent,
            user_message_id: userMessageId,
            assistant_message_id: aiMessageId,
          }).then(() => {
            queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
            queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId!) })
          }).catch((persistError) => {
            console.error('Failed to persist initial notebook deep research exchange:', persistError)
          })
          void pollDeepResearchJob({
              jobId: content.jobId,
              queryClient,
              onUpdate: (_content, job) => {
                if (notebookIdRef.current !== notebookId) return
                const nextContent = formatDeepResearchProgress(message, deepResearchOptions!, content.jobId, job)
                setMessages((prev) => prev.map((m) => m.id === aiMessageId ? { ...m, content: nextContent } : m))
              },
              onComplete: (_content, job) => {
              const finalContent = formatDeepResearchResult(message, deepResearchOptions!, job)
              if (notebookIdRef.current === notebookId) {
                setMessages((prev) => prev.map((m) => m.id === aiMessageId ? { ...m, content: finalContent } : m))
              }
              // Persist even if the user navigated away from this notebook, so
              // the report isn't lost when only the local view changed.
              void chatApi.persistExchange(sessionId!, {
                user_message: userMessage.content,
                assistant_message: finalContent,
                user_message_id: userMessageId,
                assistant_message_id: aiMessageId,
              }).then(() => {
                queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
                queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId!) })
              }).catch((persistError) => {
                console.error('Failed to persist completed notebook deep research exchange:', persistError)
              })
            },
            onFailure: (_content, job) => {
                const failureContent = formatDeepResearchFailure(
                  message,
                  deepResearchOptions!,
                  content.jobId,
                  job?.error ?? (typeof _content === 'string' ? _content : undefined),
              )
              if (notebookIdRef.current === notebookId) {
                setMessages((prev) => prev.map((m) => m.id === aiMessageId ? { ...m, content: failureContent } : m))
              }
              void chatApi.persistExchange(sessionId!, {
                user_message: userMessage.content,
                assistant_message: failureContent,
                user_message_id: userMessageId,
                assistant_message_id: aiMessageId,
              }).catch((persistError) => {
                console.error('Failed to persist failed notebook deep research exchange:', persistError)
              })
            },
            }).catch((pollError) => {
              console.error('Failed to poll deep research job:', pollError)
            })
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
            await appendAndPersistAssistant(content)
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
            await appendAndPersistAssistant(content)
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
            await appendAndPersistAssistant(content)
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
            await appendAndPersistAssistant(content)
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
            await appendAndPersistAssistant(content)
            return
          }
        }

        const instruction = routerDecision?.instruction || detectTextAgentInstruction(visualQuery)
        if (instruction) {
          activeTextAgentContext = {
            name: preferredAgent ?? 'text_instruction',
            instruction,
            startedAt: performance.now(),
          }
          activeAgentForFailure = activeTextAgentContext.name ?? activeAgentForFailure
          logChatAgentEvent({
            surface: 'notebook_chat',
            agent: activeTextAgentContext.name ?? 'text_instruction',
            event: 'selected',
            status: 'selected',
            context: agentContext,
            message_preview: previewMessage(message),
            details: { instruction: instruction.split('\n')[0] },
          })
        }

        const startedAt = activeTextAgentContext.startedAt ?? performance.now()
        if (isVisualFile(visualFile)) {
          activeAgentForFailure = 'multimodal'
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
              mode: agentOptions?.vision?.mode ?? 'auto',
            },
          })
        }

        const agentQuery = instruction
          ? `${visualQuery.trim()}\n\n${instruction}`
          : applyTextAgentInstruction(visualQuery)
        const rawContext = await buildContext(agentQuery)

        if (!file && !isVisualFile(visualFile)) {
          const body = await chatApi.sendMessageStream({
            session_id: sessionId!,
            message,
            context: rawContext,
            model_override: modelOverride ?? (currentSession?.model_override ?? undefined),
            agent_instruction: instruction,
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
                timestamp: new Date().toISOString(),
              }
              setMessages((prev) => [...prev, initial])
            }
          }

          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const events = buffer.split('\n\n')
            buffer = events.pop() ?? ''
            for (const evt of events) {
              const line = evt.split('\n').find((l) => l.startsWith('data: '))
              if (!line) continue
              try {
                const data = JSON.parse(line.slice(6))
                if (data.type === 'delta') {
                  ensureAiMessage()
                  aiContent += data.content || ''
                  setMessages((prev) =>
                    prev.map((m) => m.id === aiMessageId ? { ...m, content: aiContent } : m),
                  )
                } else if (data.type === 'complete') {
                  ensureAiMessage()
                  aiContent = data.content || aiContent
                  setMessages((prev) =>
                    prev.map((m) => m.id === aiMessageId ? { ...m, content: aiContent } : m),
                  )
                } else if (data.type === 'error') {
                  throw new Error(data.message || 'Stream error')
                }
              } catch (parseError) {
                if (!(parseError instanceof SyntaxError)) throw parseError
              }
            }
          }

          if (activeTextAgentContext.instruction && activeTextAgentContext.startedAt) {
            logChatAgentEvent({
              surface: 'notebook_chat',
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

          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
          await refetchCurrentSession()
          return
        }

        const contextText = [
          formatContext(rawContext),
          buildRecentChatContext(messages),
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
          surface: agentContext.surface,
          run_id: agentContext.runId,
          notebook_id: agentContext.notebookId,
          model_id: agentContext.modelId,
        })

        const content = await formatMultimodalResponse(result)
        logChatAgentEvent({
          surface: 'notebook_chat',
          agent: isVisualFile(visualFile)
            ? 'multimodal'
            : (activeTextAgentContext.name ?? preferredAgent ?? 'notebook_chat'),
          event: 'tool_call',
          status: 'success',
          context: agentContext,
          duration_ms: Math.round(performance.now() - startedAt),
          file: fileMetadata(visualFile),
          details: {
            route: result.route,
            engine: result.engine,
            text_instruction: Boolean(activeTextAgentContext.instruction),
            has_image_result: Boolean(result.image_base64),
            has_video_result: Boolean(result.video_base64),
          },
        })
        if (isVisualFile(visualFile)) {
          lastVisualFileRef.current = visualFile
          lastVisualQueryRef.current = visualQuery
          lastVisualContextRef.current = content
        }
        await appendAndPersistAssistant(content)
      } catch (err: unknown) {
        const error = err as { response?: { data?: { detail?: string } }; message?: string }
        console.error('Multimodal chat error:', error)
        const messageText =
          error.response?.data?.detail || error.message || 'Failed to send message'
        logChatAgentEvent({
          surface: 'notebook_chat',
          agent: activeAgentForFailure,
          event: 'tool_call',
          status: 'failure',
          context: agentContext,
          duration_ms: activeTextAgentContext.startedAt
            ? Math.round(performance.now() - activeTextAgentContext.startedAt)
            : undefined,
          file: fileMetadata(visualFile),
          details: {
            error: messageText,
            text_instruction: Boolean(activeTextAgentContext.instruction),
          },
        })
        toast.error(messageText)
        await appendAndPersistAssistant(
          `Não consegui analisar o pedido. Detalhe técnico: ${messageText}`,
          'ai-error',
        )
      } finally {
        setIsSending(false)
      }
    },
    [buildContext, currentSession, currentSessionId, messages, notebookId, pendingModelOverride, queryClient, refetchCurrentSession, t],
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

  const switchSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId)
  }, [])

  const createSession = useCallback((title?: string) => {
    return createSessionMutation.mutate({
      title,
      model_override: pendingModelOverride,
    })
  }, [createSessionMutation, pendingModelOverride])

  const updateSession = useCallback((sessionId: string, data: UpdateNotebookChatSessionRequest) => {
    return updateSessionMutation.mutate({ sessionId, data })
  }, [updateSessionMutation])

  const deleteSession = useCallback((sessionId: string) => {
    return deleteSessionMutation.mutate(sessionId)
  }, [deleteSessionMutation])

  const setModelOverride = useCallback((model: string | null) => {
    if (currentSessionId) {
      updateSessionMutation.mutate({
        sessionId: currentSessionId,
        data: { model_override: model },
      })
    } else {
      setPendingModelOverride(model)
    }
  }, [currentSessionId, updateSessionMutation])

  return {
    sessions,
    currentSession: currentSession || sessions.find((session) => session.id === currentSessionId),
    currentSessionId,
    messages,
    isSending,
    loadingSessions,
    tokenCount,
    charCount,
    pendingModelOverride,
    sendMessage,
    clearMessages,
    buildContext,
    createSession,
    updateSession,
    deleteSession,
    switchSession,
    setModelOverride,
    refetchSessions,
  }
}
