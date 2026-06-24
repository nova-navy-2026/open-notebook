'use client'

import { useState } from 'react'
import Image from 'next/image'
import { useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { NotebookResponse } from '@/lib/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Archive, ArchiveRestore, Trash2, FolderCog, Users } from 'lucide-react'
import { useUpdateNotebook } from '@/lib/hooks/use-notebooks'
import { NotebookDeleteDialog } from './NotebookDeleteDialog'
import { ShareNotebookDialog } from '@/components/notebooks/ShareNotebookDialog'
import { formatDistanceToNow } from 'date-fns'
import { getDateLocale } from '@/lib/utils/date-locale'
import { InlineEdit } from '@/components/common/InlineEdit'
import { useTranslation } from '@/lib/hooks/use-translation'

interface NotebookHeaderProps {
  notebook: NotebookResponse
  /** Opens the "edit sources" panel (sources are hidden by default). */
  onEditSources?: () => void
}

export function NotebookHeader({ notebook, onEditSources }: NotebookHeaderProps) {
  const { t, language } = useTranslation()
  const router = useRouter()
  const { resolvedTheme } = useTheme()
  const dfLocale = getDateLocale(language)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [showShareDialog, setShowShareDialog] = useState(false)

  const logoSrc = resolvedTheme === 'dark' ? '/logo_dark.png' : '/logo_light.png'

  const goBack = () => router.push('/notebooks')

  const updateNotebook = useUpdateNotebook()

  const handleUpdateName = async (name: string) => {
    if (!name || name === notebook.name) return
    
    await updateNotebook.mutateAsync({
      id: notebook.id,
      data: { name }
    })
  }

  const handleUpdateDescription = async (description: string) => {
    if (description === notebook.description) return
    
    await updateNotebook.mutateAsync({
      id: notebook.id,
      data: { description: description || undefined }
    })
  }

  const handleArchiveToggle = () => {
    updateNotebook.mutate({
      id: notebook.id,
      data: { archived: !notebook.archived }
    })
  }

  return (
    <>
      <div className="border-b pb-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              {/* Navy logo — returns to the notebooks list (immersive exit). */}
              <button
                type="button"
                onClick={goBack}
                aria-label={t.notebooks.backToNotebooks}
                title={t.notebooks.backToNotebooks}
                className="shrink-0 rounded-md p-1 hover:bg-accent/50 transition-colors"
              >
                <Image
                  src={logoSrc}
                  alt="NNBook"
                  width={32}
                  height={32}
                  style={{ width: 'auto', height: 'auto' }}
                />
              </button>
              <div className="flex-1 min-w-0 mr-2">
                <InlineEdit
                  id="notebook-name"
                  name="notebook-name"
                  value={notebook.name}
                  onSave={handleUpdateName}
                  className="text-2xl font-bold"
                  inputClassName="text-2xl font-bold"
                  placeholder={t.notebooks.namePlaceholder}
                />
              </div>
              {notebook.archived && (
                <Badge variant="secondary">{t.notebooks.archived}</Badge>
              )}
              {notebook.collaborative && (
                <Badge variant="outline" className="gap-1">
                  <Users className="h-3 w-3" />
                  {t.collaboration.collaborative}
                </Badge>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowShareDialog(true)}
              >
                <Users className="h-4 w-4 mr-2" />
                {notebook.is_owner === false
                  ? t.collaboration.members
                  : t.collaboration.share}
                {notebook.collaborative && notebook.member_count
                  ? ` (${notebook.member_count})`
                  : ''}
              </Button>
              {onEditSources && (
                <Button variant="outline" size="sm" onClick={onEditSources}>
                  <FolderCog className="h-4 w-4 mr-2" />
                  {t.notebooks.editSources}
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={handleArchiveToggle}
              >
                {notebook.archived ? (
                  <>
                    <ArchiveRestore className="h-4 w-4 mr-2" />
                    {t.notebooks.unarchive}
                  </>
                ) : (
                  <>
                    <Archive className="h-4 w-4 mr-2" />
                    {t.notebooks.archive}
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowDeleteDialog(true)}
                className="text-red-600 hover:text-red-700"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                {t.common.delete}
              </Button>
            </div>
          </div>
          
          <InlineEdit
            id="notebook-description"
            name="notebook-description"
            value={notebook.description || ''}
            onSave={handleUpdateDescription}
            className="text-muted-foreground"
            inputClassName="text-muted-foreground"
            placeholder={t.notebooks.addDescription}
            multiline
            emptyText={t.notebooks.addDescription}
          />
          
          <div className="text-sm text-muted-foreground">
            {t.common.created.replace('{time}', formatDistanceToNow(new Date(notebook.created), { addSuffix: true, locale: dfLocale }))} • 
            {t.common.updated.replace('{time}', formatDistanceToNow(new Date(notebook.updated), { addSuffix: true, locale: dfLocale }))}
          </div>
        </div>
      </div>

      <NotebookDeleteDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        notebookId={notebook.id}
        notebookName={notebook.name}
        redirectAfterDelete
      />

      <ShareNotebookDialog
        notebook={notebook}
        open={showShareDialog}
        onOpenChange={setShowShareDialog}
      />
    </>
  )
}