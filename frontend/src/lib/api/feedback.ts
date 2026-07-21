import apiClient from './client'

export interface ResponseFeedbackPayload {
  assistant_content: string
  user_question?: string
  comment?: string
  session_id?: string
  notebook_id?: string
  surface?: 'notebook_chat' | 'global_chat' | 'source_chat' | string
}

export const feedbackApi = {
  /** Report that the current user disliked an assistant answer. */
  reportResponse: async (data: ResponseFeedbackPayload) => {
    const response = await apiClient.post<{ ok: boolean; flag_id?: string }>(
      '/feedback/response',
      data,
    )
    return response.data
  },
}

export default feedbackApi
