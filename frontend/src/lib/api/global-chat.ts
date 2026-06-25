import apiClient from './client'
import { getApiUrl } from '@/lib/config'
import {
  GlobalChatSession,
  GlobalChatSessionWithMessages,
  CreateGlobalChatSessionRequest,
  UpdateGlobalChatSessionRequest,
  NotebookChatMessage,
  GlobalChatContextStats,
} from '@/lib/types/api'

export const globalChatApi = {
  listSessions: async () => {
    const response = await apiClient.get<GlobalChatSession[]>(
      `/global-chat/sessions`
    )
    return response.data
  },

  createSession: async (data: CreateGlobalChatSessionRequest) => {
    const response = await apiClient.post<GlobalChatSession>(
      `/global-chat/sessions`,
      data
    )
    return response.data
  },

  getSession: async (sessionId: string) => {
    const response = await apiClient.get<GlobalChatSessionWithMessages>(
      `/global-chat/sessions/${sessionId}`
    )
    return response.data
  },

  updateSession: async (sessionId: string, data: UpdateGlobalChatSessionRequest) => {
    const response = await apiClient.put<GlobalChatSession>(
      `/global-chat/sessions/${sessionId}`,
      data
    )
    return response.data
  },

  generateTitle: async (sessionId: string, message: string) => {
    const response = await apiClient.post<GlobalChatSession>(
      `/global-chat/sessions/${sessionId}/generate-title`,
      { message }
    )
    return response.data
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
    const response = await apiClient.post<GlobalChatSessionWithMessages>(
      `/global-chat/sessions/${sessionId}/messages`,
      data
    )
    return response.data
  },

  deleteSession: async (sessionId: string) => {
    await apiClient.delete(`/global-chat/sessions/${sessionId}`)
  },

  sendMessage: async (data: { session_id: string; message: string; model_override?: string; agent_instruction?: string; app_language?: string }) => {
    const response = await apiClient.post<{
      session_id: string
      messages: NotebookChatMessage[]
      context_stats?: GlobalChatContextStats
    }>(
      `/global-chat/execute`,
      data
    )
    return response.data
  },

  sendMessageStream: async (data: { session_id: string; message: string; model_override?: string; agent_instruction?: string; app_language?: string }) => {
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
    // Hit the FastAPI backend directly, bypassing the Next.js rewrite proxy
    // which buffers SSE responses (the whole reply would otherwise appear at
    // once instead of streaming token-by-token). Same approach as search/ask.
    let apiUrl = await getApiUrl()
    if (!apiUrl && typeof window !== 'undefined') {
      apiUrl = `${window.location.protocol}//${window.location.hostname}:5055`
    }
    const response = await fetch(`${apiUrl}/api/global-chat/execute/stream`, {
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
}

export default globalChatApi
