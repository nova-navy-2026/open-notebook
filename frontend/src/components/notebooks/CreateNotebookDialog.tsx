'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { useCreateNotebook } from '@/lib/hooks/use-notebooks'
import { useNavyDocuments } from '@/lib/hooks/use-navy-docs'
import { useTranslation } from '@/lib/hooks/use-translation'
import { NavyDocsSection } from '@/components/notebooks/NavyDocsSection'

const createNotebookSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  description: z.string().optional(),
})

type CreateNotebookFormData = z.infer<typeof createNotebookSchema>

interface CreateNotebookDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateNotebookDialog({ open, onOpenChange }: CreateNotebookDialogProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const createNotebook = useCreateNotebook()
  const { data: navyData } = useNavyDocuments()
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set())
  const {
    register,
    handleSubmit,
    formState: { errors, isValid },
    reset,
  } = useForm<CreateNotebookFormData>({
    resolver: zodResolver(createNotebookSchema),
    mode: 'onChange',
    defaultValues: {
      name: '',
      description: '',
    },
  })

  const closeDialog = () => onOpenChange(false)
  const [step, setStep] = useState<1 | 2>(1)

  const handleDocSelectionChange = useCallback(
    (docId: string, selected: boolean) => {
      setSelectedDocIds((prev) => {
        const next = new Set(prev)
        if (selected) {
          if (next.size >= 15) return prev // enforce max 15
          next.add(docId)
        } else {
          next.delete(docId)
        }
        return next
      })
    },
    [],
  )

  const handleSelectAll = useCallback(
    (selected: boolean) => {
      if (selected && navyData?.documents) {
        const ids = navyData.documents.slice(0, 15).map((d) => d.doc_id)
        setSelectedDocIds(new Set(ids))
      } else {
        setSelectedDocIds(new Set())
      }
    },
    [navyData],
  )

  const onSubmit = async (data: CreateNotebookFormData) => {
    const notebook = await createNotebook.mutateAsync(data)
    // Persist the chosen sources so the notebook detail page restores them
    // on first load (same storage key the detail page reads).
    try {
      if (notebook?.id) {
        localStorage.setItem(
          `notebook:${notebook.id}:selectedNavyDocIds`,
          JSON.stringify(Array.from(selectedDocIds)),
        )
      }
    } catch {
      // localStorage may be unavailable (private mode); ignore.
    }
    closeDialog()
    reset()
    setSelectedDocIds(new Set())
    setStep(1)
    if (notebook?.id) {
      router.push(`/notebooks/${encodeURIComponent(notebook.id)}`)
    }
  }

  // Advance to the source-selection step (validates name first).
  const goToSources = handleSubmit(() => setStep(2))

  useEffect(() => {
    if (!open) {
      reset()
      setSelectedDocIds(new Set())
      setStep(1)
    }
  }, [open, reset])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {step === 1 ? (
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{t.notebooks.createNew}</DialogTitle>
            <DialogDescription>{t.notebooks.createNewDesc}</DialogDescription>
          </DialogHeader>

          <form onSubmit={goToSources} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="notebook-name">{t.common.name} *</Label>
              <Input
                id="notebook-name"
                {...register('name')}
                placeholder={t.notebooks.namePlaceholder}
                autoComplete="off"
              />
              {errors.name && (
                <p className="text-sm text-destructive">{errors.name.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="notebook-description">
                {t.common.description}
              </Label>
              <Textarea
                id="notebook-description"
                {...register('description')}
                placeholder={t.notebooks.descPlaceholder}
                rows={4}
              />
            </div>

            <DialogFooter className="gap-2 sm:gap-0">
              <Button type="button" variant="outline" onClick={closeDialog}>
                {t.common.cancel}
              </Button>
              <Button type="submit" disabled={!isValid}>
                {t.common.next}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      ) : (
        <DialogContent className="sm:max-w-[720px] max-h-[88vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>{t.notebooks.selectSources}</DialogTitle>
            <DialogDescription>
              {t.notebooks.selectSourcesDesc}
            </DialogDescription>
          </DialogHeader>

          <div className="flex-1 min-h-0 overflow-y-auto rounded-md border p-2">
            <NavyDocsSection
              selectedDocIds={selectedDocIds}
              onSelectionChange={handleDocSelectionChange}
              onSelectAll={handleSelectAll}
            />
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="outline" onClick={() => setStep(1)}>
              {t.common.back}
            </Button>
            <Button
              type="button"
              onClick={handleSubmit(onSubmit)}
              disabled={createNotebook.isPending}
            >
              {createNotebook.isPending
                ? t.common.creating
                : t.notebooks.createNew}
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  )
}
