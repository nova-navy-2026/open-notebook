"use client";

import { useEffect, useState } from "react";
import { BookPlus, Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useNotebooks } from "@/lib/hooks/use-notebooks";
import { useCreateNote } from "@/lib/hooks/use-notes";
import { useTranslation } from "@/lib/hooks/use-translation";

interface SaveTranscriptToNotebookProps {
  /** The transcript text to save as the note body. */
  content: string;
  /** Title pre-filled in the dialog (user can edit before saving). */
  defaultTitle: string;
  /** Disable the trigger (e.g. no transcript available yet). */
  disabled?: boolean;
}

/**
 * Saves the current transcript as a note in a user-chosen notebook. Mirrors the
 * vision AddToNotebookDropdown pattern: a trigger button opens a dialog with a
 * title field + notebook selector, then creates the note via useCreateNote.
 */
export function SaveTranscriptToNotebook({
  content,
  defaultTitle,
  disabled,
}: SaveTranscriptToNotebookProps) {
  const { t } = useTranslation();
  const tp = t.transcriptionPage;

  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string>("");
  const [title, setTitle] = useState(defaultTitle);
  const { data: notebooks } = useNotebooks(false);
  const createNote = useCreateNote();

  // Refresh the pre-filled title whenever the dialog is (re)opened so it tracks
  // the latest user-typed document title from the page.
  useEffect(() => {
    if (open) setTitle(defaultTitle);
  }, [open, defaultTitle]);

  const handleSubmit = async () => {
    if (!selectedId || !content.trim()) return;
    await createNote.mutateAsync({
      title: title.trim() || defaultTitle,
      content: content.trim(),
      note_type: "human",
      notebook_id: selectedId,
    });
    setOpen(false);
    setSelectedId("");
  };

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        disabled={disabled}
      >
        <BookPlus className="h-4 w-4 mr-1" />
        {tp.saveToNotebook}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="!max-w-md sm:!max-w-md w-[min(480px,calc(100vw-2rem))]">
          <DialogHeader>
            <DialogTitle>{tp.saveToNotebookTitle}</DialogTitle>
            <DialogDescription>
              {tp.saveToNotebookDescription}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="note-title" className="text-xs text-muted-foreground">
                {tp.reportTitleLabel}
              </Label>
              <Input
                id="note-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={tp.reportTitlePlaceholder}
              />
            </div>

            <Select value={selectedId} onValueChange={setSelectedId}>
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    t.research?.selectNotebook ?? "Select a workspace..."
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {notebooks?.map((nb) => (
                  <SelectItem key={nb.id} value={nb.id}>
                    {nb.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={createNote.isPending}
              >
                {t.common.cancel}
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={!selectedId || createNote.isPending}
              >
                {createNote.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <BookPlus className="mr-2 h-4 w-4" />
                )}
                {createNote.isPending ? t.common.saving : t.common.save}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
