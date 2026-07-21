import type { AxiosResponse } from 'axios'

import apiClient from './client'
import { 
  SourceListResponse, 
  SourceDetailResponse, 
  SourceResponse,
  SourceStatusResponse,
  CreateSourceRequest, 
  UpdateSourceRequest 
} from '@/lib/types/api'

export const sourcesApi = {
  list: async (params?: {
    notebook_id?: string
    limit?: number
    offset?: number
    sort_by?: 'created' | 'updated'
    sort_order?: 'asc' | 'desc'
  }) => {
    const response = await apiClient.get<SourceListResponse[]>('/sources', { params })
    return response.data
  },

  get: async (id: string) => {
    const response = await apiClient.get<SourceDetailResponse>(
      `/sources/${encodeURIComponent(id)}`
    )
    return response.data
  },

  create: async (data: CreateSourceRequest & { file?: File }) => {
    // Always use FormData to match backend expectations
    const formData = new FormData()
    
    // Add basic fields
    formData.append('type', data.type)
    
    if (data.notebooks !== undefined) {
      formData.append('notebooks', JSON.stringify(data.notebooks))
    }
    if (data.notebook_id) {
      formData.append('notebook_id', data.notebook_id)
    }
    if (data.title) {
      formData.append('title', data.title)
    }
    if (data.url) {
      formData.append('url', data.url)
    }
    if (data.content) {
      formData.append('content', data.content)
    }
    if (data.transformations !== undefined) {
      formData.append('transformations', JSON.stringify(data.transformations))
    }
    if (data.language) {
      formData.append('language', data.language)
    }
    
    const dataWithFile = data as CreateSourceRequest & { file?: File }
    if (dataWithFile.file instanceof File) {
      formData.append('file', dataWithFile.file)
    }
    
    formData.append('embed', String(data.embed ?? false))
    formData.append('delete_source', String(data.delete_source ?? false))
    formData.append('async_processing', String(data.async_processing ?? false))
    
    const response = await apiClient.post<SourceResponse>('/sources', formData)
    return response.data
  },

  update: async (id: string, data: UpdateSourceRequest) => {
    const response = await apiClient.put<SourceListResponse>(
      `/sources/${encodeURIComponent(id)}`,
      data
    )
    return response.data
  },

  delete: async (id: string) => {
    await apiClient.delete(`/sources/${encodeURIComponent(id)}`)
  },

  status: async (id: string) => {
    const response = await apiClient.get<SourceStatusResponse>(
      `/sources/${encodeURIComponent(id)}/status`
    )
    return response.data
  },

  upload: async (file: File, notebook_id: string) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('notebook_id', notebook_id)
    formData.append('type', 'upload')
    formData.append('async_processing', 'true')
    if (typeof window !== 'undefined') {
      const language = localStorage.getItem('i18nextLng')
      if (language) formData.append('language', language)
    }
    
    const response = await apiClient.post<SourceResponse>('/sources', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  /**
   * Extract plain text from a document (PDF/DOCX/PPTX/…) without creating a
   * Source. Used by the chat attach button to fold a document's text into the
   * conversation context.
   */
  extractText: async (
    file: File,
  ): Promise<{ filename: string; text: string; chars: number; truncated: boolean }> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await apiClient.post<{
      filename: string
      text: string
      chars: number
      truncated: boolean
    }>('/sources/extract-text', formData)
    return response.data
  },

  retry: async (id: string) => {
    const response = await apiClient.post<SourceResponse>(
      `/sources/${encodeURIComponent(id)}/retry`
    )
    return response.data
  },

  downloadFile: async (id: string): Promise<AxiosResponse<Blob>> => {
    return apiClient.get(`/sources/${encodeURIComponent(id)}/download`, {
      responseType: 'blob',
    })
  },
}
