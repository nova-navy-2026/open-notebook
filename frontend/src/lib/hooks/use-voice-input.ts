'use client'

import { useState, useRef, useCallback } from 'react'
import { toast } from 'sonner'
import { transcriptionApi } from '@/lib/api/transcription'

export type VoiceInputState = 'idle' | 'recording' | 'transcribing'

export function useVoiceInput({
  onTranscript,
  language,
}: {
  onTranscript: (text: string) => void
  language?: string
}) {
  const [voiceState, setVoiceState] = useState<VoiceInputState>('idle')
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const startRecording = useCallback(async () => {
    if (voiceState !== 'idle') return

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      toast.error('Sem acesso ao microfone. Verifica as permissões do browser.')
      return
    }

    const mimeType = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/mp4',
    ].find(t => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) ?? ''

    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    chunksRef.current = []

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }

    recorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop())
      setVoiceState('transcribing')

      try {
        const usedMime = recorder.mimeType || 'audio/webm'
        const ext = usedMime.includes('mp4') ? '.mp4' : usedMime.includes('ogg') ? '.ogg' : '.webm'
        const blob = new Blob(chunksRef.current, { type: usedMime })
        const file = new File([blob], `voz${ext}`, { type: usedMime })

        const result = await transcriptionApi.transcribe(file, { language })
        const text = (result.dialog || result.text || '').trim()

        if (text) {
          onTranscript(text)
        } else {
          toast.warning('Não foi possível perceber o áudio. Tenta novamente.')
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        toast.error(`Falha na transcrição: ${msg}`)
      } finally {
        setVoiceState('idle')
      }
    }

    recorder.start()
    mediaRecorderRef.current = recorder
    setVoiceState('recording')
  }, [voiceState, onTranscript, language])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }, [])

  const handleMicClick = useCallback(() => {
    if (voiceState === 'idle') void startRecording()
    else if (voiceState === 'recording') stopRecording()
    // transcribing: button is disabled
  }, [voiceState, startRecording, stopRecording])

  return { voiceState, handleMicClick }
}
