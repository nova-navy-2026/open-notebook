export interface CitationHighlight {
  start: number
  end: number
}

export interface CitedDocumentSegment {
  parent_id: string
  section_title: string
  page_start: number | null
  page_end: number | null
  char_start: number
  char_end: number
}

export interface CitedDocumentResponse {
  id: string
  doc_id: string
  title: string
  full_text: string
  highlights: CitationHighlight[]
  segments: CitedDocumentSegment[]
  document_type: string | null
  document_status: string | null
  access_scope: string | null
  classification_level: number | null
  creator_department: string | null
  source: string | null
}

export type CitationTarget =
  | { kind: 'navy'; ref: string; chunkId?: string; snippet?: string }
  | { kind: 'source'; id: string; snippet?: string }
