export type AttachmentKind = 'image' | 'video' | 'audio' | 'file'

const AUDIO_EXTENSIONS = new Set([
  'aac',
  'aif',
  'aiff',
  'flac',
  'm4a',
  'mp3',
  'oga',
  'ogg',
  'opus',
  'qt',
  'wav',
  'weba',
  'wma',
])

const IMAGE_EXTENSIONS = new Set([
  'bmp',
  'gif',
  'jpeg',
  'jpg',
  'png',
  'tif',
  'tiff',
  'webp',
])

const VIDEO_EXTENSIONS = new Set([
  'avi',
  'm4v',
  'mkv',
  'mov',
  'mp4',
  'mpeg',
  'mpg',
  'webm',
])

function extensionForName(name?: string): string {
  const match = (name || '').toLowerCase().match(/\.([a-z0-9]+)$/)
  return match?.[1] ?? ''
}

function typeForFile(file?: File | null): string {
  return (file?.type || '').toLowerCase()
}

function hasAudioSignature(file: File): boolean {
  return typeForFile(file).startsWith('audio/') || AUDIO_EXTENSIONS.has(extensionForName(file.name))
}

export function isAudioLikeFile(file?: File | null): file is File {
  if (!file) return false
  return hasAudioSignature(file)
}

export function isImageLikeFile(file?: File | null): file is File {
  if (!file || hasAudioSignature(file)) return false
  return typeForFile(file).startsWith('image/') || IMAGE_EXTENSIONS.has(extensionForName(file.name))
}

export function isVideoLikeFile(file?: File | null): file is File {
  if (!file || hasAudioSignature(file)) return false
  return typeForFile(file).startsWith('video/') || VIDEO_EXTENSIONS.has(extensionForName(file.name))
}

export function isVisualLikeFile(file?: File | null): file is File {
  return isImageLikeFile(file) || isVideoLikeFile(file)
}

export function getAttachmentKind(file?: File | null): AttachmentKind {
  if (isAudioLikeFile(file)) return 'audio'
  if (isImageLikeFile(file)) return 'image'
  if (isVideoLikeFile(file)) return 'video'
  return 'file'
}

export function getAgentFileType(file?: File | null): string | undefined {
  if (!file) return undefined
  const type = typeForFile(file)
  const kind = getAttachmentKind(file)
  if (kind === 'audio') return type.startsWith('audio/') ? file.type : 'audio/*'
  if (kind === 'image') return type.startsWith('image/') ? file.type : 'image/*'
  if (kind === 'video') return type.startsWith('video/') ? file.type : 'video/*'
  return file.type || undefined
}
