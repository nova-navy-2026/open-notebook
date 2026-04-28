'use client'

import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

interface MediaNoteViewerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string | null
  /** "image" or "video" — determines how the asset is rendered. */
  kind: 'image' | 'video'
  /** Absolute or relative URL to the media asset. */
  mediaUrl: string
  /** Plain analysis text shown below the media. */
  analysisText: string
}

/**
 * Read-only viewer for notes whose content is an image or video asset
 * produced by the "Add to Notebook" flow on the vision pages. Shows the
 * media at full size plus the analysis text — no editing affordances.
 */
export function MediaNoteViewerDialog({
  open,
  onOpenChange,
  title,
  kind,
  mediaUrl,
  analysisText,
}: MediaNoteViewerDialogProps) {
  const { t } = useTranslation()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl w-full max-h-[90vh] overflow-hidden p-0 flex flex-col">
        <DialogTitle className="border-b px-6 py-4 text-lg font-semibold">
          {title || t.common.notes}
        </DialogTitle>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {kind === 'image' ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl}
              alt={title || ''}
              className="max-w-full h-auto rounded-md border"
            />
          ) : (
            <video
              src={mediaUrl}
              controls
              className="max-w-full h-auto rounded-md border"
            />
          )}

          {analysisText.trim() && (
            <p className="text-sm whitespace-pre-wrap break-words">
              {analysisText.trim()}
            </p>
          )}
        </div>

        <div className="border-t px-6 py-4 flex justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.close}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Inspect a note's content and, if it was produced by the vision
 * "Add to Notebook" flow (i.e. embeds an image or video pointing at
 * ``/api/vision/note-asset/<file>``), return the parts needed to render
 * a read-only viewer. Returns ``null`` for ordinary text notes.
 */
export function detectMediaNote(content: string | null | undefined): {
  kind: 'image' | 'video'
  mediaUrl: string
  analysisText: string
} | null {
  if (!content) return null

  // Image: markdown ``![alt](url)`` whose URL points to the note-asset endpoint.
  const imageMatch = content.match(
    /!\[[^\]]*\]\((\S*\/api\/vision\/note-asset\/[^)\s]+)\)/,
  )
  if (imageMatch) {
    const mediaUrl = imageMatch[1]
    const analysisText = content.replace(imageMatch[0], '').trim()
    return { kind: 'image', mediaUrl, analysisText }
  }

  // Video: link ``[label](url)`` whose URL points to the note-asset endpoint
  // and ends with a known video extension.
  const videoMatch = content.match(
    /\[[^\]]*\]\((\S*\/api\/vision\/note-asset\/[^)\s]+\.(?:mp4|webm|mov))\)/i,
  )
  if (videoMatch) {
    const mediaUrl = videoMatch[1]
    const analysisText = content.replace(videoMatch[0], '').trim()
    return { kind: 'video', mediaUrl, analysisText }
  }

  return null
}
