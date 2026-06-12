import { apiClient } from './client'

// Types
export interface NavyDocument {
  doc_id: string
  chunk_count: number
  source: string
  sample_section: string
  // Governance metadata for hierarchical grouping in the UI.
  document_type?: string
  document_status?: string
  access_scope?: string
  classification_level?: number | null
  creator_department?: string
}

export interface NavyDocumentListResponse {
  documents: NavyDocument[]
  total: number
}

export interface NavySearchRequest {
  query: string
  doc_ids?: string[]
  k?: number
}

export interface NavySearchResult {
  doc_id: string
  content: string
  source: string
  section_title: string
  page_start?: number
  page_end?: number
  score: number
}

export interface NavySearchResponse {
  results: NavySearchResult[]
  total: number
}

// API functions
export const navyDocsApi = {
  /** List all unique documents in the navy corpus */
  list: async (): Promise<NavyDocumentListResponse> => {
    const response = await apiClient.get<NavyDocumentListResponse>('/navy-docs')
    return response.data
  },

  /** Search the navy corpus with BM25 */
  search: async (request: NavySearchRequest): Promise<NavySearchResponse> => {
    const response = await apiClient.post<NavySearchResponse>('/navy-docs/search', request)
    return response.data
  },
}
