import apiClient from './client'

export interface MultimodalRequest {
  query: string
  context?: string
  mode?: string
  file?: File
  force_engine?: 'sam3' | 'rfdetr'
  surface?: 'global_chat' | 'notebook_chat'
  run_id?: string
  session_id?: string
  notebook_id?: string
  model_id?: string
  language?: string
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
    if (data.force_engine) form.append('force_engine', data.force_engine)
    if (data.surface) form.append('surface', data.surface)
    if (data.run_id) form.append('run_id', data.run_id)
    if (data.session_id) form.append('session_id', data.session_id)
    if (data.notebook_id) form.append('notebook_id', data.notebook_id)
    if (data.model_id) form.append('model_id', data.model_id)
    if (data.language) form.append('language', data.language)
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
