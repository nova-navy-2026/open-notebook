import apiClient from './client'

export interface ChartRequest {
  query: string
  data?: string
  file?: File
  model_id?: string
  surface?: 'global_chat' | 'notebook_chat'
  run_id?: string
  session_id?: string
  notebook_id?: string
}

export interface ChartResponse {
  text: string
  image_base64?: string | null
  spec?: Record<string, unknown> | null
  table_preview?: string | null
}

export interface DataProfileResponse {
  text: string
  table_preview?: string | null
  profile: Record<string, unknown>
}

export const chartsApi = {
  generate: async (data: ChartRequest): Promise<ChartResponse> => {
    const form = new FormData()
    form.append('query', data.query)
    if (data.data) form.append('data', data.data)
    if (data.model_id) form.append('model_id', data.model_id)
    if (data.surface) form.append('surface', data.surface)
    if (data.run_id) form.append('run_id', data.run_id)
    if (data.session_id) form.append('session_id', data.session_id)
    if (data.notebook_id) form.append('notebook_id', data.notebook_id)
    if (data.file) form.append('file', data.file)
    const response = await apiClient.post<ChartResponse>('/charts/generate', form)
    return response.data
  },

  profile: async (data: ChartRequest): Promise<DataProfileResponse> => {
    const form = new FormData()
    form.append('query', data.query)
    if (data.data) form.append('data', data.data)
    if (data.model_id) form.append('model_id', data.model_id)
    if (data.surface) form.append('surface', data.surface)
    if (data.run_id) form.append('run_id', data.run_id)
    if (data.session_id) form.append('session_id', data.session_id)
    if (data.notebook_id) form.append('notebook_id', data.notebook_id)
    if (data.file) form.append('file', data.file)
    const response = await apiClient.post<DataProfileResponse>('/charts/profile', form)
    return response.data
  },
}
