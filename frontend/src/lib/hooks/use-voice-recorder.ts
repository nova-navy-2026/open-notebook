/**
 * useVoiceRecorder
 *
 * Records a short clip from the user's microphone and transcribes it through
 * the existing `/api/transcription/transcribe` endpoint (Whisper / configured
 * STT model). It performs lightweight, in-browser voice-activity detection
 * (VAD) so the recording stops automatically a moment after the user stops
 * talking — no fixed-length recording and no extra clicks required.
 *
 * The heavy lifting (Whisper) lives on the backend; this hook only deals with
 * capturing audio and deciding when speech has ended.
 *
 * Notes / gotchas:
 * - `getUserMedia` requires a secure context (https or http://localhost). On a
 *   remote host reached over plain http the browser hides `mediaDevices`, which
 *   surfaces here as the `unsupported` error.
 * - MediaRecorder mime support differs by browser (Chrome/Firefox → webm/opus,
 *   Safari → mp4). We pick the first supported type and name the upload with the
 *   matching extension because the backend validates by file suffix.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { transcriptionApi } from "@/lib/api/transcription";

export type VoiceRecorderStatus =
  | "idle"
  | "requesting"
  | "listening"
  | "transcribing";

export type VoiceRecorderError =
  | "unsupported"
  | "permission-denied"
  | "no-speech"
  | "empty-transcript"
  | "transcription-failed";

export interface UseVoiceRecorderOptions {
  /** Called with the trimmed transcript once a clip is transcribed. */
  onTranscript: (text: string) => void;
  /** Called for any recoverable error so the UI can show a toast. */
  onError?: (error: VoiceRecorderError) => void;
  /** Optional ISO-639-1 language hint; omitted → server auto-detects. */
  language?: string;
  surface?: "global_chat" | "notebook_chat";
  notebookId?: string;
  /** Silence (after speech) before auto-stopping. Default 1500ms. */
  silenceTimeoutMs?: number;
  /** Give up if no speech is detected within this window. Default 7000ms. */
  noSpeechTimeoutMs?: number;
  /** Hard cap on a single recording. Default 60000ms. */
  maxDurationMs?: number;
}

type FinishMode = "transcribe" | "discard";

function pickMimeType(): { mimeType: string; ext: string } {
  const candidates: Array<{ mimeType: string; ext: string }> = [
    { mimeType: "audio/webm;codecs=opus", ext: "webm" },
    { mimeType: "audio/webm", ext: "webm" },
    { mimeType: "audio/ogg;codecs=opus", ext: "ogg" },
    { mimeType: "audio/mp4", ext: "mp4" },
  ];
  if (
    typeof MediaRecorder !== "undefined" &&
    typeof MediaRecorder.isTypeSupported === "function"
  ) {
    for (const candidate of candidates) {
      if (MediaRecorder.isTypeSupported(candidate.mimeType)) return candidate;
    }
  }
  // Let the browser choose its default container/codec.
  return { mimeType: "", ext: "webm" };
}

export function useVoiceRecorder(options: UseVoiceRecorderOptions) {
  const {
    silenceTimeoutMs = 1500,
    noSpeechTimeoutMs = 7000,
    maxDurationMs = 60000,
  } = options;

  const [status, setStatus] = useState<VoiceRecorderStatus>("idle");
  // Smoothed mic level (0..1) for the listening animation.
  const [level, setLevel] = useState(0);

  // Keep the latest callbacks/options without re-creating start().
  const optsRef = useRef(options);
  optsRef.current = options;

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const intervalRef = useRef<number | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeRef = useRef("");
  const extRef = useRef("webm");

  const startTimeRef = useRef(0);
  const lastSpeechRef = useRef(0);
  const hasSpokenRef = useRef(false);
  const speechFramesRef = useRef(0);
  const noiseFloorRef = useRef(0);
  const finishModeRef = useRef<FinishMode>("transcribe");
  const stoppingRef = useRef(false);

  const clearVadLoop = useCallback(() => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const teardownAudio = useCallback(() => {
    clearVadLoop();
    if (analyserRef.current) {
      try {
        analyserRef.current.disconnect();
      } catch {
        /* noop */
      }
      analyserRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, [clearVadLoop]);

  const transcribeBlob = useCallback(async () => {
    const blob = new Blob(chunksRef.current, {
      type: mimeRef.current || "audio/webm",
    });
    chunksRef.current = [];

    // Too small to contain real speech (e.g. user clicked but said nothing).
    if (blob.size < 1500) {
      setStatus("idle");
      optsRef.current.onError?.("empty-transcript");
      return;
    }

    setStatus("transcribing");
    try {
      const file = new File([blob], `voice-input.${extRef.current}`, {
        type: blob.type || mimeRef.current || "audio/webm",
      });
      const result = await transcriptionApi.transcribe(file, {
        language: optsRef.current.language,
        surface: optsRef.current.surface,
        notebook_id: optsRef.current.notebookId,
      });
      const text = (result.text ?? "").trim();
      if (text) {
        optsRef.current.onTranscript(text);
      } else {
        optsRef.current.onError?.("empty-transcript");
      }
    } catch {
      optsRef.current.onError?.("transcription-failed");
    } finally {
      setStatus("idle");
    }
  }, []);

  const beginStop = useCallback(
    (mode: FinishMode) => {
      if (stoppingRef.current) return;
      stoppingRef.current = true;
      finishModeRef.current = mode;
      clearVadLoop();
      setLevel(0);

      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        // onstop handles teardown + (optionally) transcription.
        recorder.stop();
      } else {
        teardownAudio();
        setStatus("idle");
      }
    },
    [clearVadLoop, teardownAudio],
  );

  const start = useCallback(async () => {
    if (status !== "idle") return;

    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      optsRef.current.onError?.("unsupported");
      return;
    }

    // Reset per-recording state.
    stoppingRef.current = false;
    hasSpokenRef.current = false;
    speechFramesRef.current = 0;
    noiseFloorRef.current = 0;
    chunksRef.current = [];
    finishModeRef.current = "transcribe";

    setStatus("requesting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      setStatus("idle");
      optsRef.current.onError?.("permission-denied");
      return;
    }
    streamRef.current = stream;

    const { mimeType, ext } = pickMimeType();
    mimeRef.current = mimeType;
    extRef.current = ext;

    let recorder: MediaRecorder;
    try {
      recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
    } catch {
      recorder = new MediaRecorder(stream);
    }
    recorderRef.current = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      teardownAudio();
      if (finishModeRef.current === "discard") {
        chunksRef.current = [];
        setStatus("idle");
        return;
      }
      void transcribeBlob();
    };
    recorder.start(100); // gather data in 100ms chunks

    // Set up voice-activity detection. If this fails we still record and rely
    // on a manual stop / the max-duration cap.
    let buffer: Uint8Array | null = null;
    try {
      const AudioCtor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const audioCtx = new AudioCtor();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.4;
      source.connect(analyser);
      analyserRef.current = analyser;
      buffer = new Uint8Array(analyser.fftSize);
    } catch {
      analyserRef.current = null;
    }

    startTimeRef.current = Date.now();
    lastSpeechRef.current = Date.now();
    setStatus("listening");

    intervalRef.current = window.setInterval(() => {
      const now = Date.now();
      const elapsed = now - startTimeRef.current;
      const analyser = analyserRef.current;

      if (analyser && buffer) {
        analyser.getByteTimeDomainData(buffer);
        let sumSquares = 0;
        for (let i = 0; i < buffer.length; i++) {
          const deviation = (buffer[i] - 128) / 128;
          sumSquares += deviation * deviation;
        }
        const rms = Math.sqrt(sumSquares / buffer.length);
        setLevel(Math.min(1, rms * 6));

        if (elapsed < 400) {
          // Calibrate the ambient noise floor before judging speech.
          noiseFloorRef.current = Math.max(noiseFloorRef.current, rms);
        } else {
          const threshold = Math.min(
            0.08,
            Math.max(0.015, noiseFloorRef.current * 2.2 + 0.008),
          );
          if (rms > threshold) {
            speechFramesRef.current += 1;
            // Require a couple of frames to avoid triggering on transient clicks.
            if (speechFramesRef.current >= 2) {
              hasSpokenRef.current = true;
              lastSpeechRef.current = now;
            }
          } else {
            speechFramesRef.current = 0;
          }
        }
      }

      if (hasSpokenRef.current && now - lastSpeechRef.current > silenceTimeoutMs) {
        beginStop("transcribe");
        return;
      }
      if (!hasSpokenRef.current && elapsed > noSpeechTimeoutMs) {
        optsRef.current.onError?.("no-speech");
        beginStop("discard");
        return;
      }
      if (elapsed > maxDurationMs) {
        beginStop(hasSpokenRef.current ? "transcribe" : "discard");
      }
    }, 50);
  }, [
    status,
    silenceTimeoutMs,
    noSpeechTimeoutMs,
    maxDurationMs,
    beginStop,
    teardownAudio,
    transcribeBlob,
  ]);

  /** Toggle for the button: start when idle, finish (transcribe) when listening. */
  const toggle = useCallback(() => {
    if (status === "idle") {
      void start();
    } else if (status === "listening") {
      beginStop("transcribe");
    }
  }, [status, start, beginStop]);

  // Hard teardown on unmount: never transcribe after the component is gone.
  useEffect(() => {
    return () => {
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        recorder.onstop = null;
        try {
          recorder.stop();
        } catch {
          /* noop */
        }
      }
      if (audioCtxRef.current) {
        audioCtxRef.current.close().catch(() => {});
        audioCtxRef.current = null;
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
    };
  }, []);

  return { status, level, start, toggle, stop: () => beginStop("transcribe") };
}
