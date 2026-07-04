"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
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
import { BookmarkPlus, Loader2 } from "lucide-react";
import { useSaveResearchAsNote } from "@/lib/hooks/use-research";
import { QUERY_KEYS } from "@/lib/api/query-client";
import { useTranslation } from "@/lib/hooks/use-translation";
import apiClient from "@/lib/api/client";

interface SaveToNotebookDialogProps {
  jobId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SaveToNotebookDialog({
  jobId,
  open,
  onOpenChange,
}: SaveToNotebookDialogProps) {
  const { t } = useTranslation();
  const saveAsNote = useSaveResearchAsNote();
  const [selectedNotebookId, setSelectedNotebookId] = useState("");

  const { data: notebooks } = useQuery({
    queryKey: QUERY_KEYS.notebooks,
    queryFn: async () => {
      const res = await apiClient.get("/notebooks");
      return res.data;
    },
    enabled: open,
  });

  const handleSave = async () => {
    if (!jobId || !selectedNotebookId) return;
    await saveAsNote.mutateAsync({
      research_id: jobId,
      notebook_id: selectedNotebookId,
    });
    onOpenChange(false);
    setSelectedNotebookId("");
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setSelectedNotebookId("");
      }}
    >
      <DialogContent className="!max-w-md sm:!max-w-md w-[min(480px,calc(100vw-2rem))]">
        <DialogHeader>
          <DialogTitle>
            {t.research?.saveToNotebook ?? "Save to Workspace"}
          </DialogTitle>
          <DialogDescription>
            {t.research?.saveToNotebookDesc ??
              "Choose a workspace to save this research report as a note."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <Select
            value={selectedNotebookId}
            onValueChange={setSelectedNotebookId}
          >
            <SelectTrigger>
              <SelectValue
                placeholder={
                  t.research?.selectNotebook ?? "Select a workspace..."
                }
              />
            </SelectTrigger>
            <SelectContent>
              {(
                notebooks as Array<{ id: string; name: string }> | undefined
              )?.map((nb) => (
                <SelectItem key={nb.id} value={nb.id}>
                  {nb.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t.common?.cancel ?? "Cancel"}
            </Button>
            <Button
              onClick={handleSave}
              disabled={!selectedNotebookId || saveAsNote.isPending}
            >
              {saveAsNote.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <BookmarkPlus className="mr-2 h-4 w-4" />
              )}
              {t.research?.save ?? "Save"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
