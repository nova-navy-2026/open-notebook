import { describe, expect, it } from 'vitest'
import {
  getAgentFileType,
  getAttachmentKind,
  isAudioLikeFile,
  isVisualLikeFile,
} from './file-kind'

function file(name: string, type = ''): File {
  return { name, type, size: 123 } as File
}

describe('file kind helpers', () => {
  it('treats audio extensions as audio even when the browser reports a video MIME type', () => {
    const audio = file('meeting.m4a', 'video/mp4')

    expect(isAudioLikeFile(audio)).toBe(true)
    expect(isVisualLikeFile(audio)).toBe(false)
    expect(getAttachmentKind(audio)).toBe('audio')
    expect(getAgentFileType(audio)).toBe('audio/*')
  })

  it('treats audio-only QuickTime recordings as audio', () => {
    const audio = file('New Recording.qt', 'video/quicktime')

    expect(isAudioLikeFile(audio)).toBe(true)
    expect(isVisualLikeFile(audio)).toBe(false)
    expect(getAttachmentKind(audio)).toBe('audio')
    expect(getAgentFileType(audio)).toBe('audio/*')
  })

  it('keeps regular video files visual', () => {
    const video = file('inspection.mp4', 'video/mp4')

    expect(isAudioLikeFile(video)).toBe(false)
    expect(isVisualLikeFile(video)).toBe(true)
    expect(getAttachmentKind(video)).toBe('video')
    expect(getAgentFileType(video)).toBe('video/mp4')
  })
})
