/**
 * Transcription store.
 *
 * Holds the in-flight + last-completed state for the Transcription page
 * (Whisper + optional pyannote diarization). Mirrors the pattern used by
 * the vision-store so that switching tabs / unmounting the page does not
 * cancel an in-flight request nor lose the inputs / results.
 *
 * NOT persisted to localStorage because `File` / blob-URL state cannot be
 * serialised across reloads.
 */

import { create } from "zustand";

import { getApiUrl } from "@/lib/config";
import { useAuthStore } from "@/lib/stores/auth-store";

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  speaker?: string | null;
}

export interface TranscriptionResult {
  text: string;
  segments: TranscriptSegment[];
  speakers: string[];
  dialog?: string | null;
  diarized: boolean;
  language?: string | null;
}

export interface TranscriptionCapabilities {
  diarization_available: boolean;
  diarization_unavailable_reason?: string | null;
  local_whisper_available: boolean;
  allowed_extensions: string[];
  max_audio_mb: number;
}

interface TranscriptionState {
  audio: File | null;
  audioPreview: string | null; // object URL for <audio> playback
  language: string;
  diarize: boolean;
  numSpeakers: string; // empty = auto
  isLoading: boolean;
  result: TranscriptionResult | null;
  error: string | null;
  capabilities: TranscriptionCapabilities | null;
}

interface TranscriptionActions {
  setAudio: (file: File | null) => void;
  setLanguage: (lang: string) => void;
  setDiarize: (v: boolean) => void;
  setNumSpeakers: (v: string) => void;
  setError: (msg: string | null) => void;
  fetchCapabilities: () => Promise<void>;
  submit: () => Promise<void>;
  clear: () => void;
}

const initialState: TranscriptionState = {
  audio: null,
  audioPreview: null,
  language: "",
  diarize: false,
  numSpeakers: "",
  isLoading: false,
  result: null,
  error: null,
  capabilities: null,
};

export const useTranscriptionStore = create<
  TranscriptionState & TranscriptionActions
>((set, get) => ({
  ...initialState,

  setAudio: (file) => {
    const prev = get().audioPreview;
    if (prev) {
      try {
        URL.revokeObjectURL(prev);
      } catch {
        /* noop */
      }
    }
    if (!file) {
      set({ audio: null, audioPreview: null });
      return;
    }
    const url = URL.createObjectURL(file);
    set({ audio: file, audioPreview: url, error: null });
  },

  setLanguage: (lang) => set({ language: lang }),
  setDiarize: (v) => set({ diarize: v }),
  setNumSpeakers: (v) => set({ numSpeakers: v }),
  setError: (msg) => set({ error: msg }),

  fetchCapabilities: async () => {
    try {
      const apiUrl = await getApiUrl();
      const token = useAuthStore.getState().token;
      const response = await fetch(
        `${apiUrl}/api/transcription/capabilities`,
        {
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        },
      );
      if (!response.ok) return;
      const data = (await response.json()) as TranscriptionCapabilities;
      set({ capabilities: data });
    } catch {
      /* non-fatal */
    }
  },

  submit: async () => {
    const { audio, language, diarize, numSpeakers } = get();
    if (!audio) {
      set({ error: "Please provide an audio file." });
      return;
    }

    set({ isLoading: true, error: null, result: null });

    try {
      const formData = new FormData();
      formData.append("audio", audio);
      if (language.trim()) formData.append("language", language.trim());
      formData.append("diarize", diarize ? "true" : "false");
      if (diarize && numSpeakers.trim()) {
        const n = parseInt(numSpeakers.trim(), 10);
        if (!Number.isNaN(n) && n > 0) {
          formData.append("num_speakers", String(n));
        }
      }

      const apiUrl = await getApiUrl();
      const token = useAuthStore.getState().token;
      const response = await fetch(
        `${apiUrl}/api/transcription/transcribe`,
        {
          method: "POST",
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: formData,
        },
      );

      if (!response.ok) {
        const err = await response.json().catch(() => null);
        throw new Error(
          err?.detail || `Server error (${response.status})`,
        );
      }

      const data = (await response.json()) as TranscriptionResult;
      set({ result: data, isLoading: false });
    } catch (e) {
      set({
        error:
          e instanceof Error
            ? e.message || "Failed to transcribe audio."
            : "Failed to transcribe audio.",
        isLoading: false,
      });
    }
  },

  clear: () => {
    const prev = get().audioPreview;
    if (prev) {
      try {
        URL.revokeObjectURL(prev);
      } catch {
        /* noop */
      }
    }
    set({ ...initialState, capabilities: get().capabilities });
  },
}));
