import apiClient from './client'

export interface MultimodalRequest {
  query: string
  context?: string
  mode?: string
  file?: File
}

export interface MultimodalResponse {
  text: string
  route?: string
  engine?: string
  image_base64?: string | null
  video_base64?: string | null
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
  saveNoteAsset: async (dataUrl: string): Promise<string> => {
    const response = await apiClient.post<{ url: string }>('/vision/note-asset', {
      data_url: dataUrl,
    })
    return response.data.url
  },
}
