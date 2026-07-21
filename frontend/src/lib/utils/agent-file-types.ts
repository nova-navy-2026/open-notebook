// Single source of truth for the file types each agent accepts, so the SAME
// agent offers the SAME types everywhere it can be invoked (e.g. the
// transcription agent in the chat clip button and on the Transcription page,
// or the vision agent in chat and on the Vision pages).
//
// These lists mirror the backend gates:
//   - audio     → whisper_server ALLOWED_EXTENSIONS / transcription router
//   - image     → vision router ALLOWED_IMAGE_EXTENSIONS
//   - video     → vision router ALLOWED_VIDEO_EXTENSIONS
//   - data      → charts router ALLOWED_EXTENSIONS (data profiler / graphs)
//   - document  → sources router CHAT_DOCUMENT_EXTENSIONS (extract-text)
// Keep them in sync when a backend gate changes.

export const AUDIO_EXTENSIONS = [
  '.wav', '.mp3', '.m4a', '.flac', '.ogg', '.oga', '.webm', '.mp4', '.aac', '.wma',
]
export const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp']
export const VIDEO_EXTENSIONS = ['.mp4', '.webm', '.mov', '.avi']
export const DATA_EXTENSIONS = [
  '.csv', '.tsv', '.txt', '.json', '.jsonl', '.ndjson', '.xls', '.xlsx',
]
export const DOCUMENT_EXTENSIONS = [
  '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.rtf', '.odt', '.epub', '.md',
  '.markdown', '.html', '.htm',
]

export const AUDIO_MIME = [
  'audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/x-m4a',
  'audio/flac', 'audio/ogg', 'audio/aac', 'audio/webm', 'audio/x-ms-wma',
]
export const IMAGE_MIME = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp']
export const VIDEO_MIME = [
  'video/mp4', 'video/webm', 'video/quicktime', 'video/x-msvideo',
]
export const DATA_MIME = [
  'text/csv', 'text/tab-separated-values', 'application/json',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
]
export const DOCUMENT_MIME = [
  'application/pdf', 'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/rtf', 'application/vnd.oasis.opendocument.text',
  'application/epub+zip', 'text/markdown', 'text/html',
]

/** Join groups of MIME types / extensions into a de-duplicated `accept` string. */
function toAccept(...groups: string[][]): string {
  return Array.from(new Set(groups.flat())).join(',')
}

// Per-agent accept strings. Use these anywhere the agent's file picker lives.
export const AUDIO_ACCEPT = toAccept(AUDIO_MIME, AUDIO_EXTENSIONS)
export const IMAGE_ACCEPT = toAccept(IMAGE_MIME, IMAGE_EXTENSIONS)
export const VIDEO_ACCEPT = toAccept(VIDEO_MIME, VIDEO_EXTENSIONS)
export const VISION_ACCEPT = toAccept(IMAGE_MIME, VIDEO_MIME, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS)

// The chat clip button can reach every agent, so it accepts the union of all.
export const CHAT_ATTACH_ACCEPT = toAccept(
  IMAGE_MIME, VIDEO_MIME, AUDIO_MIME, DATA_MIME, DOCUMENT_MIME,
  IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, DATA_EXTENSIONS, DOCUMENT_EXTENSIONS,
)
