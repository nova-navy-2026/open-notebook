// Research types for the NOVA-Researcher integration

export type ResearchStatus = "pending" | "running" | "completed" | "failed";

export interface ReportTypeInfo {
  value: string;
  label: string;
  description: string;
  speed?: "quick" | "balanced" | "in-depth";
}

export interface ToneInfo {
  value: string;
  label: string;
  description: string;
}

export interface SourceInfo {
  value: string;
  label: string;
  description: string;
}

export interface ResearchGenerateRequest {
  query: string;
  report_type: string;
  report_source: string;
  tone: string;
  source_urls: string[];
  notebook_id?: string | null;
  model_id?: string;
  use_amalia: boolean;
  run_in_background: boolean;
  // Optional human-readable response language (e.g. "English"). Used by
  // retrieval-free flows such as meeting minutes (ATA).
  language?: string;
  // Transcript document style: "ata" | "conversation" | "summary" | "literal".
  report_style?: string;
  // Optional user-supplied document title.
  title?: string;
  // Audio-report flow: force the retrieval-free transcript path for ANY report
  // type (no OpenSearch/web). report_type + tone shape the prompt instead.
  transcript_only?: boolean;
}

export interface ResearchJobSubmitResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface ResearchResultData {
  report: string;
  source_urls: string[];
  research_costs: number;
  images: string[];
  tone?: string;
  model_id?: string;
  retrieved_documents?: RetrievedDocument[];
}

export interface RetrievedDocument {
  title: string;
  source: string;
  snippet: string;
}

export interface ResearchJob {
  id: string;
  query: string;
  report_type: string;
  status: ResearchStatus;
  progress: string;
  progress_pct: number;
  created_at: string;
  updated_at?: string | null;
  error?: string | null;
  has_result?: boolean;
  result?: ResearchResultData | null;
  tone?: string;
  model_id?: string;
}

export interface ResearchSyncResult {
  id: string;
  query: string;
  report_type: string;
  report: string;
  source_urls: string[];
  research_costs: number;
  images: string[];
  status: string;
  created_at: string;
  error?: string | null;
}

export interface SaveAsNoteRequest {
  research_id: string;
  notebook_id: string;
  title?: string;
}

export interface SaveAsNoteResponse {
  success: boolean;
  note_id: string;
  message: string;
}

// Status helpers
export const ACTIVE_RESEARCH_STATUSES: ResearchStatus[] = [
  "pending",
  "running",
];

export function isResearchActive(status: ResearchStatus): boolean {
  return ACTIVE_RESEARCH_STATUSES.includes(status);
}
