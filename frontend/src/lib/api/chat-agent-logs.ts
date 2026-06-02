import apiClient from './client'

export interface ChatAgentLogPayload {
  surface: 'global_chat' | 'notebook_chat'
  agent: string
  event: string
  status?: 'started' | 'selected' | 'success' | 'skipped' | 'failure' | 'info'
  run_id?: string
  session_id?: string
  notebook_id?: string
  model_id?: string
  message_preview?: string
  file?: {
    name?: string
    type?: string
    size?: number
  }
  duration_ms?: number
  details?: Record<string, unknown>
}

export type ChatAgentName = string

export interface ChatAgentRouteRequest {
  surface: 'global_chat' | 'notebook_chat'
  message: string
  run_id?: string
  session_id?: string
  notebook_id?: string
  model_id?: string
  has_file?: boolean
  file_type?: string
  file_name?: string
  visual_follow_up?: boolean
  deep_research_enabled?: boolean
}

export interface ChatAgentRouteResponse {
  agent: ChatAgentName
  confidence: number
  reason: string
  parameters: Record<string, unknown>
  handler: string
  instruction?: string | null
  source: 'gemma_router' | 'fallback'
}

export interface ChatAgentCatalogItem {
  name: string
  description: string
  handler: string
  has_instruction: boolean
  parameters: Record<string, string>
}

export const chatAgentLogsApi = {
  list: async () => {
    const response = await apiClient.get<ChatAgentCatalogItem[]>('/chat-agents')
    return response.data
  },

  log: async (payload: ChatAgentLogPayload) => {
    const response = await apiClient.post<{
      success: boolean
      structured_log_written?: boolean
      log_path?: string
    }>(
      '/chat-agents/log',
      payload,
    )
    return response.data
  },

  route: async (payload: ChatAgentRouteRequest) => {
    const response = await apiClient.post<ChatAgentRouteResponse>(
      '/chat-agents/route',
      payload,
    )
    return response.data
  },
}
