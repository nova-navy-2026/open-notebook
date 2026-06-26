import apiClient from './client'

export interface MultimodalRequest {
  query: string
  context?: string
  mode?: string
  file?: File
  force_engine?: 'sam3' | 'rfdetr'
  surface?: 'global_chat' | 'notebook_chat'
  run_id?: string
  session_id?: string
  notebook_id?: string
  model_id?: string
  language?: string
}

export interface MultimodalResponse {
  text: string
  route?: string
  engine?: string
  image_base64?: string | null
  video_base64?: string | null
}

export const multimodalApi = {
  chat: async (data: MultimodalRequest): Promise<MultimodalResponse> => {
    const form = new FormData()
    form.append('query', data.query)
    if (data.context) form.append('context', data.context)
    form.append('mode', data.mode ?? 'chat')
    if (data.force_engine) form.append('force_engine', data.force_engine)
    if (data.surface) form.append('surface', data.surface)
    if (data.run_id) form.append('run_id', data.run_id)
    if (data.session_id) form.append('session_id', data.session_id)
    if (data.notebook_id) form.append('notebook_id', data.notebook_id)
    if (data.model_id) form.append('model_id', data.model_id)
    if (data.language) form.append('language', data.language)
    if (data.file) form.append('file', data.file)
    const response = await apiClient.post<
      MultimodalResponse & { async?: boolean; job_id?: string; target?: string }
    >('/vision/multimodal', form)
    const body = response.data

    // Fast path: images and general video return a result inline (unchanged).
    if (!body?.async || !body.job_id) {
      return body
    }

    // Async path: a long-running video job was enqueued (e.g. tracking /
    // segmentation). Poll until it finishes so no single request is held open
    // long enough to be reset by a proxy (Cloudflare ~100s, nginx). The return
    // type is identical, so callers (chat hooks) need no changes.
    const jobId = body.job_id
    const engine = body.engine ?? ''
    const target = body.target ?? ''
    const POLL_INTERVAL_MS = 2000
    const MAX_WAIT_MS = 15 * 60 * 1000
    const startedAt = Date.now()

    // eslint-disable-next-line no-constant-condition
    while (true) {
      if (Date.now() - startedAt > MAX_WAIT_MS) {
        throw new Error('Video analysis timed out. Please try a shorter clip.')
      }
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))

      const statusRes = await apiClient
        .get<{
          status: string
          text?: string
          route?: string
          engine?: string
          video_base64?: string | null
          error?: string
        }>(`/vision/multimodal/jobs/${encodeURIComponent(jobId)}`, {
          params: { query: data.query, engine, target },
        })
        .catch(() => null)

      if (!statusRes) continue // transient blip — keep polling
      const s = statusRes.data

      if (s.status === 'completed') {
        return {
          text: s.text ?? '',
          route: s.route,
          engine: s.engine,
          video_base64: s.video_base64 ?? null,
        }
      }
      if (s.status === 'failed') {
        throw new Error(s.error || 'Video analysis failed.')
      }
      // status === 'processing' -> keep polling
    }
  },
  saveNoteAsset: async (dataUrl: string): Promise<string> => {
    const response = await apiClient.post<{ url: string }>('/vision/note-asset', {
      data_url: dataUrl,
    })
    return response.data.url
  },
}
