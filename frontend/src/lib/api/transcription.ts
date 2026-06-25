import apiClient from './client'

export interface TranscriptSegment {
  start: number
  end: number
  text: string
  speaker?: string | null
}

export interface TranscriptionResult {
  text: string
  segments?: TranscriptSegment[]
  speakers?: string[]
  dialog?: string | null
  diarized?: boolean
  language?: string | null
  provider?: string
  model?: string
}

export interface TranslationResult {
  translated_text: string
  target_language: string
}

export const transcriptionApi = {
  transcribe: async (
    file: File,
    options?: {
      language?: string
      diarize?: boolean
      numSpeakers?: number
      surface?: 'global_chat' | 'notebook_chat'
      run_id?: string
      session_id?: string
      notebook_id?: string
      model_id?: string
    },
  ) => {
    const form = new FormData()
    form.append('audio', file)
    if (options?.language) form.append('language', options.language)
    form.append('diarize', options?.diarize ? 'true' : 'false')
    if (options?.numSpeakers) {
      form.append('num_speakers', String(options.numSpeakers))
    }
    if (options?.surface) form.append('surface', options.surface)
    if (options?.run_id) form.append('run_id', options.run_id)
    if (options?.session_id) form.append('session_id', options.session_id)
    if (options?.notebook_id) form.append('notebook_id', options.notebook_id)
    if (options?.model_id) form.append('model_id', options.model_id)
    const response = await apiClient.post<TranscriptionResult>(
      '/transcription/transcribe',
      form,
    )
    return response.data
  },

  translate: async (text: string, targetLanguage: string): Promise<TranslationResult> => {
    const response = await apiClient.post<TranslationResult>('/transcription/translate', {
      text,
      target_language: targetLanguage,
    })
    return response.data
  },
}
