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

export const transcriptionApi = {
  transcribe: async (
    file: File,
    options?: {
      language?: string
      diarize?: boolean
      numSpeakers?: number
    },
  ) => {
    const form = new FormData()
    form.append('audio', file)
    if (options?.language) form.append('language', options.language)
    form.append('diarize', options?.diarize ? 'true' : 'false')
    if (options?.numSpeakers) {
      form.append('num_speakers', String(options.numSpeakers))
    }
    const response = await apiClient.post<TranscriptionResult>(
      '/transcription/transcribe',
      form,
    )
    return response.data
  },
}
