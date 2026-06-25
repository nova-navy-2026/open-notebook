import apiClient from './client'
import { getApiUrl } from '@/lib/config'
import {
  NotebookChatSession,
  NotebookChatSessionWithMessages,
  CreateNotebookChatSessionRequest,
  UpdateNotebookChatSessionRequest,
  SendNotebookChatMessageRequest,
  NotebookChatMessage,
  BuildContextRequest,
  BuildContextResponse,
} from '@/lib/types/api'

export const chatApi = {
  // Session management
  listSessions: async (notebookId: string) => {
    const response = await apiClient.get<NotebookChatSession[]>(
      `/chat/sessions`,
      { params: { notebook_id: notebookId } }
    )
    return response.data
  },

  createSession: async (data: CreateNotebookChatSessionRequest) => {
    const response = await apiClient.post<NotebookChatSession>(
      `/chat/sessions`,
      data
    )
    return response.data
  },

  getSession: async (sessionId: string) => {
    const response = await apiClient.get<NotebookChatSessionWithMessages>(
      `/chat/sessions/${sessionId}`
    )
    return response.data
  },

  updateSession: async (sessionId: string, data: UpdateNotebookChatSessionRequest) => {
    const response = await apiClient.put<NotebookChatSession>(
      `/chat/sessions/${sessionId}`,
      data
    )
    return response.data
  },

  generateTitle: async (sessionId: string, message: string) => {
    const response = await apiClient.post<NotebookChatSession>(
      `/chat/sessions/${sessionId}/generate-title`,
      { message }
    )
    return response.data
  },

  deleteSession: async (sessionId: string) => {
    await apiClient.delete(`/chat/sessions/${sessionId}`)
  },

  persistExchange: async (
    sessionId: string,
    data: {
      user_message: string
      assistant_message: string
      user_message_id?: string
      assistant_message_id?: string
    },
  ) => {
    const response = await apiClient.post<NotebookChatSessionWithMessages>(
      `/chat/sessions/${sessionId}/messages`,
      data,
    )
    return response.data
  },

  // Messaging (synchronous, no streaming)
  sendMessage: async (data: SendNotebookChatMessageRequest) => {
    const response = await apiClient.post<{
      session_id: string
      messages: NotebookChatMessage[]
    }>(
      `/chat/execute`,
      data
    )
    return response.data
  },

  // Streaming variant — returns the raw response body for SSE consumption.
  sendMessageStream: async (data: SendNotebookChatMessageRequest) => {
    let token: string | null = null
    if (typeof window !== 'undefined') {
      const authStorage = localStorage.getItem('auth-storage')
      if (authStorage) {
        try {
          const { state } = JSON.parse(authStorage)
          if (state?.token) token = state.token
        } catch (error) {
          console.error('Error parsing auth storage:', error)
        }
      }
    }
    // Prefer hitting the FastAPI backend directly (bypasses the Next.js rewrite
    // proxy that can buffer SSE). But ONLY when a reachable absolute API URL is
    // configured — in relative-path deployments (API bound to 127.0.0.1:5055,
    // reachable only via the Next.js proxy) we MUST use the relative path, or
    // the browser fetch fails with "Failed to fetch".
    const apiBase = await getApiUrl()
    const streamUrl = apiBase
      ? `${apiBase}/api/chat/execute/stream`
      : `/api/chat/execute/stream`
    const response = await fetch(streamUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    return response.body
  },

  buildContext: async (data: BuildContextRequest) => {
    const response = await apiClient.post<BuildContextResponse>(
      `/chat/context`,
      data
    )
    return response.data
  },
}

export default chatApi
