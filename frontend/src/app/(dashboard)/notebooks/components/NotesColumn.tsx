'use client'

import { useState, useMemo, useRef } from 'react'
import { NoteResponse } from '@/lib/types/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Plus, StickyNote, Bot, User, MoreVertical, Trash2, Image as ImageIcon, Video as VideoIcon, PlayCircle } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { EmptyState } from '@/components/common/EmptyState'
import { Badge } from '@/components/ui/badge'
import { NoteEditorDialog } from './NoteEditorDialog'
import {
  MediaNoteViewerDialog,
  detectMediaNote,
  useResolvedAssetUrl,
} from '@/components/vision/MediaNoteViewerDialog'
import { getDateLocale } from '@/lib/utils/date-locale'
import { formatDistanceToNow } from 'date-fns'
import { ContextToggle } from '@/components/common/ContextToggle'
import { ContextMode } from '../[id]/page'
import { useDeleteNote } from '@/lib/hooks/use-notes'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { CollapsibleColumn, createCollapseButton } from '@/components/notebooks/CollapsibleColumn'
import { useNotebookColumnsStore } from '@/lib/stores/notebook-columns-store'
import { useTranslation } from '@/lib/hooks/use-translation'

interface NotesColumnProps {
  notes?: NoteResponse[]
  isLoading: boolean
  notebookId: string
  contextSelections?: Record<string, ContextMode>
  onContextModeChange?: (noteId: string, mode: ContextMode) => void
}

/**
 * Renders a thumbnail for a video by seeking to a random frame once
 * metadata is available. Falls back to the first frame if seeking fails.
 */
function VideoThumbnail({ src, className }: { src: string; className?: string }) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const seekedRef = useRef(false)
  const resolved = useResolvedAssetUrl(src)

  const handleLoadedMetadata = () => {
    const video = videoRef.current
    if (!video || seekedRef.current) return
    const duration = video.duration
    if (!isFinite(duration) || duration <= 0) return
    // Pick a frame between 10% and 90% of the duration
    const min = duration * 0.1
    const max = duration * 0.9
    const target = min + Math.random() * (max - min)
    try {
      video.currentTime = target
      seekedRef.current = true
    } catch {
      // Seeking can fail on some codecs/browsers; first frame remains.
    }
  }

  return (
    <video
      ref={videoRef}
      src={resolved}
      muted
      playsInline
      preload="metadata"
      crossOrigin="anonymous"
      onLoadedMetadata={handleLoadedMetadata}
      className={className}
    />
  )
}

/**
 * Renders an image thumbnail using the live API base URL so the
 * markdown-stored path keeps working when the frontend is served from a
 * different host than the API.
 */
function ImageThumbnail({
  src,
  alt,
  className,
}: {
  src: string
  alt: string
  className?: string
}) {
  const resolved = useResolvedAssetUrl(src)
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={resolved} alt={alt} className={className} />
}

export function NotesColumn({
  notes,
  isLoading,
  notebookId,
  contextSelections,
  onContextModeChange
}: NotesColumnProps) {
  const { t, language } = useTranslation()
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [editingNote, setEditingNote] = useState<NoteResponse | null>(null)
  const [viewingMediaNote, setViewingMediaNote] = useState<NoteResponse | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [noteToDelete, setNoteToDelete] = useState<string | null>(null)

  const deleteNote = useDeleteNote()

  // Collapsible column state
  const { notesCollapsed, toggleNotes } = useNotebookColumnsStore()
  const collapseButton = useMemo(
    () => createCollapseButton(toggleNotes, t.notebooks.agentNotes),
    [toggleNotes, t.notebooks.agentNotes]
  )

  const handleDeleteClick = (noteId: string) => {
    setNoteToDelete(noteId)
    setDeleteDialogOpen(true)
  }

  const handleDeleteConfirm = async () => {
    if (!noteToDelete) return

    try {
      await deleteNote.mutateAsync(noteToDelete)
      setDeleteDialogOpen(false)
      setNoteToDelete(null)
    } catch (error) {
      console.error('Failed to delete note:', error)
    }
  }

  return (
    <>
      <CollapsibleColumn
        isCollapsed={notesCollapsed}
        onToggle={toggleNotes}
        collapsedIcon={StickyNote}
        collapsedLabel={t.notebooks.agentNotes}
      >
        <Card className="h-full flex flex-col flex-1 overflow-hidden">
          <CardHeader className="pb-3 flex-shrink-0">
            <div className="flex items-center justify-between gap-2 min-w-0">
              <CardTitle className="text-lg truncate">{t.notebooks.agentNotes}</CardTitle>
              <div className="flex items-center gap-1 flex-shrink-0">
                <Button
                  size="sm"
                  onClick={() => {
                    setEditingNote(null)
                    setShowAddDialog(true)
                  }}
                >
                  <Plus className="h-4 w-4" />
                  <span className="hidden xl:inline ml-1">{t.common.writeNote}</span>
                </Button>
                {collapseButton}
              </div>
            </div>
          </CardHeader>

          <CardContent className="flex-1 overflow-y-auto min-h-0">
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <LoadingSpinner />
              </div>
            ) : !notes || notes.length === 0 ? (
              <EmptyState
                icon={StickyNote}
                title={t.notebooks.noNotesYet}
                description={t.sources.createFirstNote}
              />
            ) : (
              <div className="space-y-3">
                {notes.map((note) => {
                  const media = detectMediaNote(note.content)
                  const isAi = note.note_type === 'ai'
                  const TypeIcon = media
                    ? media.kind === 'image'
                      ? ImageIcon
                      : VideoIcon
                    : isAi
                      ? Bot
                      : User
                  const typeLabel = media
                    ? media.kind === 'image'
                      ? 'Imagem'
                      : 'Vídeo'
                    : isAi
                      ? t.common.aiGenerated
                      : t.common.human
                  const typeBadgeClass = media
                    ? media.kind === 'image'
                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
                      : 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                    : isAi
                      ? 'bg-primary/10 text-primary border-primary/30'
                      : 'bg-muted text-muted-foreground border-border'
                  return (
                  <div
                    key={note.id}
                    className="p-3 border rounded-lg card-hover group relative cursor-pointer"
                    onClick={() => {
                      if (media) {
                        setViewingMediaNote(note)
                      } else {
                        setEditingNote(note)
                      }
                    }}
                  >
                    <div className="flex gap-3 items-stretch">
                      {media ? (
                        <div className="relative flex-shrink-0 w-20 self-stretch min-h-[5rem] rounded-md overflow-hidden border bg-muted">
                          {media.kind === 'image' ? (
                            <ImageThumbnail
                              src={media.mediaUrl}
                              alt={note.title || ''}
                              className="absolute inset-0 w-full h-full object-cover"
                            />
                          ) : (
                            <>
                              <VideoThumbnail
                                src={media.mediaUrl}
                                className="absolute inset-0 w-full h-full object-cover"
                              />
                              <div className="absolute inset-0 flex items-center justify-center bg-black/20">
                                <PlayCircle className="h-7 w-7 text-white drop-shadow" />
                              </div>
                            </>
                          )}
                        </div>
                      ) : (
                        <div
                          className={`relative flex-shrink-0 w-20 self-stretch min-h-[5rem] rounded-md overflow-hidden border flex items-center justify-center ${
                            isAi
                              ? 'bg-primary/10 border-primary/30'
                              : 'bg-muted border-border'
                          }`}
                        >
                          <TypeIcon
                            className={`h-8 w-8 ${
                              isAi ? 'text-primary' : 'text-muted-foreground'
                            }`}
                          />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between mb-2 gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <TypeIcon className={`h-4 w-4 flex-shrink-0 ${isAi && !media ? 'text-primary' : media?.kind === 'image' ? 'text-emerald-600 dark:text-emerald-400' : media?.kind === 'video' ? 'text-purple-600 dark:text-purple-400' : 'text-muted-foreground'}`} />
                            <Badge variant="outline" className={`text-xs ${typeBadgeClass}`}>
                              {typeLabel}
                            </Badge>
                          </div>

                          <div className="flex items-center gap-2 flex-shrink-0">
                            <span className="text-xs text-muted-foreground hidden sm:inline">
                              {formatDistanceToNow(new Date(note.updated), { 
                                addSuffix: true,
                                locale: getDateLocale(language)
                              })}
                            </span>

                            {/* Context toggle - only show if handler provided */}
                            {onContextModeChange && contextSelections?.[note.id] && (
                              <div onClick={(event) => event.stopPropagation()}>
                                <ContextToggle
                                  mode={contextSelections[note.id]}
                                  hasInsights={false}
                                  onChange={(mode) => onContextModeChange(note.id, mode)}
                                />
                              </div>
                            )}

                            {/* Ellipsis menu for delete action */}
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <MoreVertical className="h-4 w-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-48">
                                <DropdownMenuItem
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    handleDeleteClick(note.id)
                                  }}
                                  className="text-red-600 focus:text-red-600"
                                >
                                  <Trash2 className="h-4 w-4 mr-2" />
                                  {t.notebooks.deleteNote}
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </div>
                        </div>

                        {note.title && (
                          <h4 className="text-sm font-medium mb-2 break-all">{note.title}</h4>
                        )}

                        {media ? (
                          media.analysisText && (
                            <p className="text-sm text-muted-foreground line-clamp-3 break-all">
                              {media.analysisText}
                            </p>
                          )
                        ) : (
                          note.content && (
                            <p className="text-sm text-muted-foreground line-clamp-3 break-all">
                              {note.content}
                            </p>
                          )
                        )}
                      </div>
                    </div>
                  </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </CollapsibleColumn>

      <NoteEditorDialog
        open={showAddDialog || Boolean(editingNote)}
        onOpenChange={(open) => {
          if (!open) {
            setShowAddDialog(false)
            setEditingNote(null)
          } else {
            setShowAddDialog(true)
          }
        }}
        notebookId={notebookId}
        note={editingNote ?? undefined}
      />

      {viewingMediaNote && (() => {
        const media = detectMediaNote(viewingMediaNote.content)
        if (!media) return null
        return (
          <MediaNoteViewerDialog
            open={Boolean(viewingMediaNote)}
            onOpenChange={(open) => {
              if (!open) setViewingMediaNote(null)
            }}
            title={viewingMediaNote.title}
            kind={media.kind}
            mediaUrl={media.mediaUrl}
            analysisText={media.analysisText}
          />
        )
      })()}

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={t.notebooks.deleteNote}
        description={t.notebooks.deleteNoteConfirm}
        confirmText={t.common.delete}
        onConfirm={handleDeleteConfirm}
        isLoading={deleteNote.isPending}
        confirmVariant="destructive"
      />
    </>
  )
}
