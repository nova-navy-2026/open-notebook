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

// --- Document-relationship graph -------------------------------------------

export interface TopicClass {
  id: string
  label: string
  color: string
}

export interface GraphDocumentClass {
  class: string
  count: number
}

export interface GraphDocumentNode {
  id: string
  label: string
  chunk_count: number
  classes: GraphDocumentClass[]
}

export interface GraphTopicNode {
  id: string
  label: string
  color: string
  doc_count: number
  chunk_count: number
}

export interface BipartiteEdge {
  source: string
  topic: string
  weight: number
}

export interface SimilarityEdge {
  source: string
  target: string
  weight: number
  shared: string[]
}

export interface DocumentGraphResponse {
  documents: GraphDocumentNode[]
  topics: GraphTopicNode[]
  edges_bipartite: BipartiteEdge[]
  edges_similarity: SimilarityEdge[]
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

  /** Fetch the fixed, global topic taxonomy */
  topics: async (): Promise<TopicClass[]> => {
    const response = await apiClient.get<TopicClass[]>('/navy-docs/topics')
    return response.data
  },

  /** Build the topic-clustered relationship graph for a set of documents */
  graph: async (docIds: string[]): Promise<DocumentGraphResponse> => {
    const response = await apiClient.post<DocumentGraphResponse>('/navy-docs/graph', {
      doc_ids: docIds,
    })
    return response.data
  },
}
