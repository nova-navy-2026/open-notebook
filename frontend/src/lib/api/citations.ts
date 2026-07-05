import apiClient from './client'
import { CitedDocumentResponse } from '@/lib/types/citations'

interface MaterializeCitationBody {
  ref: string
  chunk_id?: string | null
  snippet?: string | null
}

export const citationsApi = {
  materialize: async (body: MaterializeCitationBody): Promise<CitedDocumentResponse> => {
    const response = await apiClient.post<CitedDocumentResponse>('/citations/materialize', body)
    return response.data
  },

  get: async (id: string): Promise<CitedDocumentResponse> => {
    const response = await apiClient.get<CitedDocumentResponse>(
      `/citations/${encodeURIComponent(id)}`
    )
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/citations/${encodeURIComponent(id)}`)
  },
}
