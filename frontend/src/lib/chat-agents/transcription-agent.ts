import { transcriptionApi } from '@/lib/api/transcription'
import { researchApi } from '@/lib/api/research'
import {
  currentAppLanguageName,
  detectTranscriptReportStyle,
  detectTranscriptReportType,
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

    // If the user asked for a document/report (ATA, resumo, conversa,
    // transcrição literal, OR a "relatório [detalhado/aprofundado]"), turn the
    // transcript into that document in the app's language — mirroring the
    // Transcription page (same report types + styles, transcript-only). The
    // chosen report TYPE drives depth/structure; the STYLE drives the document
    // format. Otherwise return the plain transcript.
    const reportStyle = detectTranscriptReportStyle(message)
    const reportType = detectTranscriptReportType(message)
    const transcript = (result.dialog || result.text || '').trim()
    if ((reportStyle || reportType) && transcript) {
      try {
        const generated = await researchApi.generateResearch({
          query: transcript,
          // transcript_only keeps it retrieval-free (no OpenSearch/web) for ANY
          // report type — exactly like the Transcription page.
          transcript_only: true,
          report_type: reportType ?? 'meeting_minutes',
          // No explicit style word but a report type was asked for → use a
          // general "summary" document base instead of the ATA structure.
          report_style: reportStyle ?? (reportType ? 'summary' : 'ata'),
          report_source: 'local',
          tone: 'Objective',
          source_urls: [],
          model_id: context?.modelId,
          use_amalia: true,
          language: currentAppLanguageName(),
          run_in_background: false,
        })
        const report = 'report' in generated ? generated.report : ''
        if (report && report.trim()) {
          return report
        }
      } catch (genError) {
        // Fall back to the plain transcript if document generation fails.
        logChatAgentEvent({
          surface: context?.surface ?? 'global_chat',
          agent: 'transcription',
          event: 'tool_call',
          status: 'failure',
          context,
          file: fileMetadata(file),
          details: {
            stage: 'report_generation',
            report_style: reportStyle,
            error: genError instanceof Error ? genError.message : String(genError),
          },
        })
      }
    }

    return formatTranscriptionResponse(result)
  } catch (error) {
    const status = (error as { response?: { status?: number } })?.response?.status
    const errorMessage = error instanceof Error ? error.message : String(error)
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'transcription',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      file: fileMetadata(file),
      details: { error: errorMessage, http_status: status },
    })
    if (status === 413) {
      return 'O ficheiro de áudio é demasiado grande para transcrever. Tenta com um ficheiro menor.'
    }
    if (status === 415 || status === 422) {
      return 'Este formato de áudio não é suportado. Tenta com MP3, WAV, OGG ou M4A.'
    }
    if (status === 503 || status === 502) {
      return 'O serviço de transcrição não está disponível de momento. Tenta novamente mais tarde.'
    }
    return `Não consegui transcrever o ficheiro. Detalhe: ${errorMessage}`
  }
}
