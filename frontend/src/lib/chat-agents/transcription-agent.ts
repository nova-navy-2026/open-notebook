import { transcriptionApi } from '@/lib/api/transcription'
import {
  formatTranscriptionResponse,
  isAudioFile,
  isTranscriptionRequest,
  wantsDiarization,
} from '@/lib/utils/chat-agents'
import {
  fileMetadata,
  logChatAgentEvent,
  previewMessage,
  type ChatAgentRunContext,
} from '@/lib/chat-agents/logger'
import type { ChatAgentUiOptions } from '@/lib/utils/chat-agents'

export async function runTranscriptionAgent(
  message: string,
  file?: File,
  context?: ChatAgentRunContext,
  force = false,
  options?: ChatAgentUiOptions['transcription'],
): Promise<string | null> {
  if (!file || (!force && !isAudioFile(file) && !isTranscriptionRequest(message, file))) {
    return null
  }

  const diarize = options?.diarize ?? wantsDiarization(message)
  const startedAt = performance.now()
  logChatAgentEvent({
    surface: context?.surface ?? 'global_chat',
    agent: 'transcription',
    event: 'selected',
    status: 'selected',
    context,
    message_preview: previewMessage(message),
    file: fileMetadata(file),
    details: { diarize },
  })

  try {
    const result = await transcriptionApi.transcribe(file, {
      diarize,
      language: options?.language,
      numSpeakers: options?.numSpeakers,
      surface: context?.surface,
      run_id: context?.runId,
      session_id: context?.sessionId,
      notebook_id: context?.notebookId,
      model_id: context?.modelId,
    })
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'transcription',
      event: 'tool_call',
      status: 'success',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      file: fileMetadata(file),
      details: {
        diarize,
        provider: result.provider,
        model: result.model,
        language: result.language,
        chars: (result.dialog || result.text || '').length,
      },
    })
    return formatTranscriptionResponse(result)
  } catch (error) {
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'transcription',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      file: fileMetadata(file),
      details: { error: error instanceof Error ? error.message : String(error) },
    })
    throw error
  }
}
