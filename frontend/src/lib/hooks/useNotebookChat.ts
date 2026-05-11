"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getApiErrorMessage } from "@/lib/utils/error-handler";
import { useTranslation } from "@/lib/hooks/use-translation";
import { chatApi } from "@/lib/api/chat";
import { QUERY_KEYS } from "@/lib/api/query-client";
import {
  NotebookChatMessage,
  CreateNotebookChatSessionRequest,
  UpdateNotebookChatSessionRequest,
  SourceListResponse,
  NoteResponse,
} from "@/lib/types/api";
import { ContextSelections } from "@/app/(dashboard)/notebooks/[id]/page";

interface UseNotebookChatParams {
  notebookId: string;
  sources: SourceListResponse[];
  notes: NoteResponse[];
  contextSelections: ContextSelections;
  selectedNavyDocIds?: Set<string>;
}

export function useNotebookChat({
  notebookId,
  sources,
  notes,
  contextSelections,
  selectedNavyDocIds,
}: UseNotebookChatParams) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<NotebookChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [tokenCount, setTokenCount] = useState<number>(0);
  const [charCount, setCharCount] = useState<number>(0);
  // Pending model override for when user changes model before a session exists
  const [pendingModelOverride, setPendingModelOverride] = useState<
    string | null
  >(null);
  // Whether auto-select-most-recent has already run. After the user
  // explicitly deletes the active session we keep the conversation cleared.
  const autoSelectedRef = useRef(false);
  // Track which session id the local messages were last synced from, so we
  // do not overwrite optimistic messages when a freshly-created session
  // returns an empty messages array from the API.
  const syncedSessionRef = useRef<string | null>(null);
  // True while a stream is in-flight; prevents the session refetch effect
  // from clobbering the in-progress optimistic / streamed messages.
  const isSendingRef = useRef(false);

  // Fetch sessions for this notebook
  const {
    data: sessions = [],
    isLoading: loadingSessions,
    refetch: refetchSessions,
  } = useQuery({
    queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
    queryFn: () => chatApi.listSessions(notebookId),
    enabled: !!notebookId,
  });

  // Fetch current session with messages
  const { data: currentSession, refetch: refetchCurrentSession } = useQuery({
    queryKey: QUERY_KEYS.notebookChatSession(currentSessionId!),
    queryFn: () => chatApi.getSession(currentSessionId!),
    enabled: !!notebookId && !!currentSessionId,
  });

  // Update messages when current session changes. Skip while a stream is
  // in flight (we don't want to wipe the optimistic user message before the
  // backend has finished persisting it) and avoid replacing local messages
  // with an empty list freshly returned for a just-created session.
  useEffect(() => {
    if (!currentSession?.id) return;
    if (isSendingRef.current) return;
    const sessionChanged = syncedSessionRef.current !== currentSession.id;
    const serverMessages = currentSession.messages ?? [];
    if (sessionChanged) {
      setMessages(serverMessages);
      syncedSessionRef.current = currentSession.id;
      return;
    }
    // Same session: only sync when the server actually has messages, so a
    // transient empty payload (e.g. immediately after session creation)
    // does not erase optimistic / streamed messages.
    if (serverMessages.length > 0) {
      setMessages(serverMessages);
    }
  }, [currentSession]);

  // Auto-select most recent session when sessions are loaded — only on
  // the very first load. Once the user has explicitly closed/deleted the
  // active session we keep the panel cleared rather than jumping to another.
  useEffect(() => {
    if (!autoSelectedRef.current && sessions.length > 0 && !currentSessionId) {
      autoSelectedRef.current = true;
      // Sessions are sorted by created date desc from API
      const mostRecentSession = sessions[0];
      setCurrentSessionId(mostRecentSession.id);
    }
  }, [sessions, currentSessionId]);

  // Create session mutation
  const createSessionMutation = useMutation({
    mutationFn: (data: CreateNotebookChatSessionRequest) =>
      chatApi.createSession(data),
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
      });
      setCurrentSessionId(newSession.id);
      toast.success(t.chat.sessionCreated);
    },
    onError: (err: unknown) => {
      const error = err as {
        response?: { data?: { detail?: string } };
        message?: string;
      };
      toast.error(
        getApiErrorMessage(
          error.response?.data?.detail || error.message,
          (key) => t(key),
          "apiErrors.failedToCreateSession",
        ),
      );
    },
  });

  // Update session mutation
  const updateSessionMutation = useMutation({
    mutationFn: ({
      sessionId,
      data,
    }: {
      sessionId: string;
      data: UpdateNotebookChatSessionRequest;
    }) => chatApi.updateSession(sessionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
      });
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSession(currentSessionId!),
      });
      toast.success(t.chat.sessionUpdated);
    },
    onError: (err: unknown) => {
      const error = err as {
        response?: { data?: { detail?: string } };
        message?: string;
      };
      toast.error(
        getApiErrorMessage(
          error.response?.data?.detail || error.message,
          (key) => t(key),
          "apiErrors.failedToUpdateSession",
        ),
      );
    },
  });

  // Delete session mutation
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => chatApi.deleteSession(sessionId),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
      });
      // Drop the cached session so its stale messages cannot repopulate
      // the panel after we clear it below.
      queryClient.removeQueries({
        queryKey: QUERY_KEYS.notebookChatSession(deletedId),
      });
      if (currentSessionId === deletedId) {
        autoSelectedRef.current = true;
        setCurrentSessionId(null);
        setMessages([]);
      }
      toast.success(t.chat.sessionDeleted);
    },
    onError: (err: unknown) => {
      const error = err as {
        response?: { data?: { detail?: string } };
        message?: string;
      };
      toast.error(
        getApiErrorMessage(
          error.response?.data?.detail || error.message,
          (key) => t(key),
          "apiErrors.failedToDeleteSession",
        ),
      );
    },
  });

  // Build context from sources and notes based on user selections
  const buildContext = useCallback(
    async (query?: string) => {
      // Build context_config mapping IDs to selection modes
      const context_config: {
        sources: Record<string, string>;
        notes: Record<string, string>;
        navy_docs?: { doc_ids: string[] };
      } = {
        sources: {},
        notes: {},
      };

      // Map source selections
      sources.forEach((source) => {
        const mode = contextSelections.sources[source.id];
        if (mode === "insights") {
          context_config.sources[source.id] = "insights";
        } else if (mode === "full") {
          context_config.sources[source.id] = "full content";
        } else {
          context_config.sources[source.id] = "not in";
        }
      });

      // Map note selections
      notes.forEach((note) => {
        const mode = contextSelections.notes[note.id];
        if (mode === "full") {
          context_config.notes[note.id] = "full content";
        } else {
          context_config.notes[note.id] = "not in";
        }
      });

      // Include navy corpus document selections
      if (selectedNavyDocIds && selectedNavyDocIds.size > 0) {
        context_config.navy_docs = { doc_ids: Array.from(selectedNavyDocIds) };
      }

      // Call API to build context with actual content
      const response = await chatApi.buildContext({
        notebook_id: notebookId,
        context_config,
        ...(query ? { query } : {}),
      });

      // Store token and char counts
      setTokenCount(response.token_count);
      setCharCount(response.char_count);

      return response.context;
    },
    [notebookId, sources, notes, contextSelections, selectedNavyDocIds],
  );

  // Send message (synchronous, no streaming)
  const sendMessage = useCallback(
    async (message: string, modelOverride?: string) => {
      let sessionId = currentSessionId;

      // Auto-create session if none exists
      if (!sessionId) {
        try {
          const defaultTitle =
            message.length > 30 ? `${message.substring(0, 30)}...` : message;
          const newSession = await chatApi.createSession({
            notebook_id: notebookId,
            title: defaultTitle,
            // Include pending model override when creating session
            model_override: pendingModelOverride ?? undefined,
          });
          sessionId = newSession.id;
          setCurrentSessionId(sessionId);
          // Clear pending model override now that it's applied to the session
          setPendingModelOverride(null);
          queryClient.invalidateQueries({
            queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
          });
        } catch (err: unknown) {
          const error = err as {
            response?: { data?: { detail?: string } };
            message?: string;
          };
          toast.error(
            getApiErrorMessage(
              error.response?.data?.detail || error.message,
              (key) => t(key),
              "apiErrors.failedToCreateSession",
            ),
          );
          return;
        }
      }

      // Add user message optimistically
      const userMessage: NotebookChatMessage = {
        id: `temp-${Date.now()}`,
        type: "human",
        content: message,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);
      setIsSending(true);
      isSendingRef.current = true;

      try {
        // Build context (pass message as query for navy corpus BM25 search)
        const context = await buildContext(message);
        const body = await chatApi.sendMessageStream({
          session_id: sessionId,
          message,
          context,
          model_override:
            modelOverride ?? currentSession?.model_override ?? undefined,
        });

        if (!body) throw new Error("No response body");

        const reader = body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let aiMessageId: string | null = null;
        let aiContent = "";

        const ensureAiMessage = () => {
          if (!aiMessageId) {
            aiMessageId = `ai-${Date.now()}`;
            const initial: NotebookChatMessage = {
              id: aiMessageId,
              type: "ai",
              content: "",
              timestamp: new Date().toISOString(),
            };
            setMessages((prev) => [...prev, initial]);
          }
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() ?? "";
          for (const evt of events) {
            const line = evt.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue;
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === "delta") {
                ensureAiMessage();
                aiContent += data.content || "";
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMessageId ? { ...m, content: aiContent } : m,
                  ),
                );
              } else if (data.type === "complete") {
                ensureAiMessage();
                aiContent = data.content || aiContent;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMessageId ? { ...m, content: aiContent } : m,
                  ),
                );
              } else if (data.type === "error") {
                throw new Error(data.message || "Stream error");
              }
            } catch (e) {
              if (!(e instanceof SyntaxError)) throw e;
            }
          }
        }

        // Streaming finished — drop the in-flight guard BEFORE refetching the
        // session, otherwise the sync useEffect will skip the resolved server
        // payload and the UI will keep showing only the optimistic messages.
        isSendingRef.current = false;
        // Refetch current session to get persisted messages with real IDs
        await refetchCurrentSession();
      } catch (err: unknown) {
        const error = err as {
          response?: { data?: { detail?: string } };
          message?: string;
        };
        console.error("Error sending message:", error);
        toast.error(
          getApiErrorMessage(
            error.response?.data?.detail || error.message,
            (key) => t(key),
            "apiErrors.failedToSendMessage",
          ),
        );
        // Remove optimistic message on error
        setMessages((prev) =>
          prev.filter(
            (msg) => !msg.id.startsWith("temp-") && !msg.id.startsWith("ai-"),
          ),
        );
      } finally {
        setIsSending(false);
        isSendingRef.current = false;
      }
    },
    [
      notebookId,
      currentSessionId,
      currentSession,
      pendingModelOverride,
      buildContext,
      refetchCurrentSession,
      queryClient,
      t,
    ],
  );

  // Switch session
  const switchSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId);
  }, []);

  // Create session
  const createSession = useCallback(
    (title?: string) => {
      return createSessionMutation.mutate({
        notebook_id: notebookId,
        title,
      });
    },
    [createSessionMutation, notebookId],
  );

  // Update session
  const updateSession = useCallback(
    (sessionId: string, data: UpdateNotebookChatSessionRequest) => {
      return updateSessionMutation.mutate({
        sessionId,
        data,
      });
    },
    [updateSessionMutation],
  );

  // Delete session
  const deleteSession = useCallback(
    (sessionId: string) => {
      return deleteSessionMutation.mutate(sessionId);
    },
    [deleteSessionMutation],
  );

  // Set model override - handles both existing sessions and pending state
  const setModelOverride = useCallback(
    (model: string | null) => {
      if (currentSessionId) {
        // Session exists - update it directly
        updateSessionMutation.mutate({
          sessionId: currentSessionId,
          data: { model_override: model },
        });
      } else {
        // No session yet - store as pending
        setPendingModelOverride(model);
      }
    },
    [currentSessionId, updateSessionMutation],
  );

  // Update token/char counts when context selections change
  useEffect(() => {
    const updateContextCounts = async () => {
      try {
        await buildContext();
      } catch (error) {
        console.error("Error updating context counts:", error);
      }
    };
    updateContextCounts();
  }, [buildContext]);

  return {
    // State
    sessions,
    currentSession:
      currentSession || sessions.find((s) => s.id === currentSessionId),
    currentSessionId,
    messages,
    isSending,
    loadingSessions,
    tokenCount,
    charCount,
    pendingModelOverride,

    // Actions
    createSession,
    updateSession,
    deleteSession,
    switchSession,
    sendMessage,
    setModelOverride,
    refetchSessions,
  };
}
