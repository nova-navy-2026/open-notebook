import apiClient from './client'

export interface MultimodalRequest {
  query: string
  context?: string
  mode?: string
  file?: File
}

export interface MultimodalResponse {
  text: string
}

export const multimodalApi = {
  chat: async (data: MultimodalRequest): Promise<MultimodalResponse> => {
    const form = new FormData()
    form.append('query', data.query)
    if (data.context) form.append('context', data.context)
    form.append('mode', data.mode ?? 'chat')
    if (data.file) form.append('file', data.file)
    const response = await apiClient.post<MultimodalResponse>('/vision/multimodal', form)
    return response.data
  },
}
