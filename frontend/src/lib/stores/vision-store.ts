/**
 * Vision analysis store.
 *
 * Holds the in-flight + last-completed state for the Image Analysis and
 * Video Tracking pages. The store lives at the app level (zustand) so:
 *   - Switching tabs / unmounting the page does NOT lose your inputs,
 *     preview, results, or in-progress request.
 *   - A long-running analysis keeps running in the background even if the
 *     user navigates away, and the results land in the store when ready.
 *
 * NOTE: This store is intentionally NOT persisted to localStorage because
 * `File` / blob-URL state cannot be serialised across reloads. State is
 * therefore retained for the lifetime of the page (i.e. survives route
 * changes, lost on full reload).
 */

import { create } from 'zustand'

import { getApiUrl } from '@/lib/config'
import { useAuthStore } from '@/lib/stores/auth-store'

export type VisionEngine = 'sam3' | 'rfdetr'

// ────────────────────────────────────────────────────────────────────
// Image analysis
// ────────────────────────────────────────────────────────────────────

interface ImageAnalysisState {
  image: File | null
  imagePreview: string | null
  query: string
  engine: VisionEngine
  isLoading: boolean
  resultText: string | null
  resultImage: string | null
  error: string | null
}

interface ImageAnalysisActions {
  setImage: (file: File | null) => void
  setQuery: (q: string) => void
  setEngine: (e: VisionEngine) => void
  setError: (msg: string | null) => void
  submit: () => Promise<void>
  clear: () => void
}

const initialImageState: ImageAnalysisState = {
  image: null,
  imagePreview: null,
  query: '',
  engine: 'sam3',
  isLoading: false,
  resultText: null,
  resultImage: null,
  error: null,
}

export const useImageAnalysisStore = create<ImageAnalysisState & ImageAnalysisActions>((set, get) => ({
  ...initialImageState,

  setImage: (file) => {
    if (!file) {
      set({ image: null, imagePreview: null })
      return
    }
    const reader = new FileReader()
    reader.onloadend = () => {
      set({ image: file, imagePreview: reader.result as string, error: null })
    }
    reader.readAsDataURL(file)
  },

  setQuery: (q) => set({ query: q }),
  setEngine: (e) => set({ engine: e }),
  setError: (msg) => set({ error: msg }),

  submit: async () => {
    const { image, query, engine, imagePreview } = get()
    if (!image) {
      set({ error: 'Please provide an image.' })
      return
    }
    if (engine === 'sam3' && !query.trim()) {
      set({
        error:
          'SAM3 requires a query. Describe what to look for, or switch to RF-DETR for prompt-free detection.',
      })
      return
    }

    set({ isLoading: true, error: null, resultText: null, resultImage: null })

    try {
      const formData = new FormData()
      formData.append('image', image)
      formData.append('query', query)
      formData.append('engine', engine)

      const apiUrl = await getApiUrl()
      const token = useAuthStore.getState().token
      const response = await fetch(`${apiUrl}/api/vision/image-analysis`, {
        method: 'POST',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: formData,
      })

      if (!response.ok) {
        const err = await response.json().catch(() => null)
        throw new Error(err?.detail || `Server error (${response.status})`)
      }

      const data = await response.json()
      set({
        resultText: data.text || null,
        // Fall back to the original preview if the server didn't return
        // an annotated image (e.g. zero detections).
        resultImage: data.image_base64 || imagePreview,
        isLoading: false,
      })
    } catch (e) {
      set({
        error:
          e instanceof Error
            ? e.message || 'Failed to analyze image. Please try again.'
            : 'Failed to analyze image. Please try again.',
        isLoading: false,
      })
    }
  },

  clear: () => set({ ...initialImageState }),
}))

// ────────────────────────────────────────────────────────────────────
// Video tracking
// ────────────────────────────────────────────────────────────────────

interface VideoTrackingState {
  video: File | null
  videoPreview: string | null
  target: string
  engine: VisionEngine
  isLoading: boolean
  resultText: string | null
  resultVideo: string | null
  error: string | null
}

interface VideoTrackingActions {
  setVideo: (file: File | null) => void
  setTarget: (t: string) => void
  setEngine: (e: VisionEngine) => void
  setError: (msg: string | null) => void
  submit: () => Promise<void>
  clear: () => void
}

const initialVideoState: VideoTrackingState = {
  video: null,
  videoPreview: null,
  target: '',
  engine: 'sam3',
  isLoading: false,
  resultText: null,
  resultVideo: null,
  error: null,
}

export const useVideoTrackingStore = create<VideoTrackingState & VideoTrackingActions>((set, get) => ({
  ...initialVideoState,

  setVideo: (file) => {
    const prev = get().videoPreview
    if (prev) {
      try { URL.revokeObjectURL(prev) } catch { /* noop */ }
    }
    if (!file) {
      set({ video: null, videoPreview: null })
      return
    }
    const url = URL.createObjectURL(file)
    set({ video: file, videoPreview: url, error: null })
  },

  setTarget: (t) => set({ target: t }),
  setEngine: (e) => set({ engine: e }),
  setError: (msg) => set({ error: msg }),

  submit: async () => {
    const { video, target, engine } = get()
    if (!video) {
      set({ error: 'Please provide a video.' })
      return
    }
    if (engine === 'sam3' && !target.trim()) {
      set({
        error:
          'SAM3 requires a target element. Describe what to track, or switch to RF-DETR for prompt-free tracking.',
      })
      return
    }

    set({ isLoading: true, error: null, resultText: null, resultVideo: null })

    try {
      const formData = new FormData()
      formData.append('video', video)
      formData.append('target', target)
      formData.append('engine', engine)

      const apiUrl = await getApiUrl()
      const token = useAuthStore.getState().token
      const authHeader: Record<string, string> = token
        ? { Authorization: `Bearer ${token}` }
        : {}

      // 1) Submit the job — returns immediately with a job id. Tracking runs in
      // a background worker, so no single request is held open long enough to be
      // reset by a proxy (Cloudflare's ~100s cap, nginx read timeout, …).
      const submitRes = await fetch(`${apiUrl}/api/vision/video-tracking`, {
        method: 'POST',
        headers: { ...authHeader },
        body: formData,
      })

      if (!submitRes.ok) {
        const err = await submitRes.json().catch(() => null)
        throw new Error(err?.detail || `Server error (${submitRes.status})`)
      }

      const { job_id: jobId } = await submitRes.json()
      if (!jobId) throw new Error('Server did not return a job id.')

      // 2) Poll for the result. Each poll is a quick read, immune to the
      // timeouts that broke the old synchronous endpoint.
      const POLL_INTERVAL_MS = 2000
      const MAX_WAIT_MS = 15 * 60 * 1000 // safety ceiling: 15 min
      const startedAt = Date.now()

      // eslint-disable-next-line no-constant-condition
      while (true) {
        if (Date.now() - startedAt > MAX_WAIT_MS) {
          throw new Error('Video tracking timed out. Please try a shorter clip.')
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))

        const statusRes = await fetch(
          `${apiUrl}/api/vision/video-tracking/jobs/${encodeURIComponent(jobId)}`,
          { headers: { ...authHeader } },
        )
        if (!statusRes.ok) {
          // Transient proxy/network blip — keep polling rather than abort.
          continue
        }
        const data = await statusRes.json()

        if (data.status === 'completed') {
          set({
            resultText: data.text || null,
            resultVideo: data.video_base64 || null,
            isLoading: false,
          })
          return
        }
        if (data.status === 'failed') {
          throw new Error(data.error || 'Video tracking failed.')
        }
        // status === 'processing' -> loop again
      }
    } catch (e) {
      set({
        error:
          e instanceof Error
            ? e.message || 'Failed to process video. Please try again.'
            : 'Failed to process video. Please try again.',
        isLoading: false,
      })
    }
  },

  clear: () => {
    const prev = get().videoPreview
    if (prev) {
      try { URL.revokeObjectURL(prev) } catch { /* noop */ }
    }
    set({ ...initialVideoState })
  },
}))
