import apiClient from './client'
import {
  ReportTypeInfo,
  ToneInfo,
  SourceInfo,
  ResearchGenerateRequest,
  ResearchJobSubmitResponse,
  ResearchJob,
  ResearchSyncResult,
  SaveAsNoteRequest,
  SaveAsNoteResponse,
} from '@/lib/types/research'

export const researchApi = {
  /**
   * Get available report types
   */
  getReportTypes: async (): Promise<ReportTypeInfo[]> => {
    const response = await apiClient.get<ReportTypeInfo[]>('/research/report-types')
    return response.data
  },

  /**
   * Get available writing tones
   */
  getTones: async (): Promise<ToneInfo[]> => {
    const response = await apiClient.get<ToneInfo[]>('/research/tones')
    return response.data
  },

  /**
   * Get available report sources
   */
  getSources: async (): Promise<SourceInfo[]> => {
    const response = await apiClient.get<SourceInfo[]>('/research/sources')
    return response.data
  },

  /**
   * Generate a research report (background mode)
   */
  generateResearch: async (
    payload: ResearchGenerateRequest
  ): Promise<ResearchJobSubmitResponse | ResearchSyncResult> => {
    const response = await apiClient.post('/research/generate', payload)
    return response.data
  },

  /**
   * List all research jobs
   */
  listJobs: async (): Promise<{ jobs: ResearchJob[] }> => {
    const response = await apiClient.get<{ jobs: ResearchJob[] }>('/research/jobs')
    return response.data
  },

  /**
   * Get a specific research job (includes result if completed)
   */
  getJob: async (jobId: string): Promise<ResearchJob> => {
    const response = await apiClient.get<ResearchJob>(`/research/jobs/${jobId}`)
    return response.data
  },

  /**
   * Delete a research job permanently
   */
  deleteJob: async (jobId: string): Promise<void> => {
    await apiClient.delete(`/research/jobs/${jobId}`)
  },

  /**
   * Apply an edit instruction to a completed report. The revised report is
   * stored back on the job (chat + history) and the updated job is returned.
   */
  reviseJob: async (
    jobId: string,
    payload: { instruction: string; model_id?: string },
  ): Promise<ResearchJob> => {
    const response = await apiClient.post<ResearchJob>(
      `/research/jobs/${jobId}/revise`,
      payload,
    )
    return response.data
  },

  /**
   * Directly replace the report text without AI processing.
   */
  directUpdateReport: async (jobId: string, report: string): Promise<ResearchJob> => {
    const response = await apiClient.patch<ResearchJob>(
      `/research/jobs/${jobId}/report`,
      { report },
    )
    return response.data
  },

  /**
   * Save a research result as a Note in a Notebook
   */
  saveAsNote: async (payload: SaveAsNoteRequest): Promise<SaveAsNoteResponse> => {
    const response = await apiClient.post<SaveAsNoteResponse>(
      '/research/save-as-note',
      payload
    )
    return response.data
  },
}
