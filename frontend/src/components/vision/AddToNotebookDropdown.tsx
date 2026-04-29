"use client";

import { useState } from "react";
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
import { BookPlus, Loader2 } from "lucide-react";
import { useNotebooks } from "@/lib/hooks/use-notebooks";
import { useCreateNote } from "@/lib/hooks/use-notes";
import { useAuthStore } from "@/lib/stores/auth-store";
import { getApiUrl } from "@/lib/config";
import { toast } from "sonner";
import { useTranslation } from "@/lib/hooks/use-translation";

interface AddToNotebookDropdownProps {
  /** Kind of media to embed in the note. */
  mediaKind: "image" | "video";
  /** Data URL (or any URL) of the media to embed in the note. */
  mediaDataUrl: string | null;
  /** Title used for the note. */
  title: string;
  /** Optional analysis text to append below the media. */
  analysisText?: string | null;
}

/**
 * Persist a base64 data URL to the backend so it can be embedded in a note
 * via a stable HTTP URL (markdown-image / video tag friendly). Returns the
 * absolute URL to the asset.
 */
async function uploadDataUrlAsset(dataUrl: string): Promise<string> {
  const apiUrl = await getApiUrl();
  const token = useAuthStore.getState().token;
  const response = await fetch(`${apiUrl}/api/vision/note-asset`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ data_url: dataUrl }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => null);
    throw new Error(err?.detail || `Failed to save asset (${response.status})`);
  }

  const data = (await response.json()) as { url: string };
  // Store the path-only URL (e.g. "/api/vision/note-asset/<file>") so the
  // resulting markdown is portable across hosts: the renderer prepends the
  // current API base URL at view time.
  return data.url;
}

export function AddToNotebookDropdown({
  mediaKind,
  mediaDataUrl,
  title,
  analysisText,
}: AddToNotebookDropdownProps) {
  const { t } = useTranslation();
  const dt = t.addToNotebookDialog;
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const { data: notebooks } = useNotebooks(false);
  const createNote = useCreateNote();

  const buildContent = (mediaUrl: string | null) => {
    const parts: string[] = [];
    if (mediaUrl) {
      if (mediaKind === "image") {
        parts.push(`![${title}](${mediaUrl})`);
      } else {
        // Markdown link as the renderer's <video> tag may be sanitized away.
        parts.push(`[▶ ${title}](${mediaUrl})`);
      }
    }
    if (analysisText && analysisText.trim()) {
      parts.push("");
      parts.push(analysisText.trim());
    }
    return parts.join("\n\n");
  };

  const handleSubmit = async () => {
    if (!mediaDataUrl || !selectedId) return;
    setSubmitting(true);
    try {
      // If the source is already an HTTP(S) URL, use it as-is; otherwise
      // upload the data URL to obtain a stable URL.
      let assetUrl: string | null = null;
      if (mediaDataUrl.startsWith("data:")) {
        assetUrl = await uploadDataUrlAsset(mediaDataUrl);
      } else {
        assetUrl = mediaDataUrl;
      }

      await createNote.mutateAsync({
        title,
        content: buildContent(assetUrl),
        note_type: "human",
        notebook_id: selectedId,
      });

      toast.success(dt.success);
      setOpen(false);
      setSelectedId("");
    } catch (e) {
      console.error(e);
      toast.error(dt.error);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        disabled={!mediaDataUrl}
      >
        <BookPlus className="h-4 w-4 mr-1" />
        {dt.title}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="!max-w-md sm:!max-w-md w-[min(480px,calc(100vw-2rem))]">
          <DialogHeader>
            <DialogTitle>{dt.title}</DialogTitle>
            <DialogDescription>{dt.description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <Select value={selectedId} onValueChange={setSelectedId}>
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    t.research?.selectNotebook ?? "Select a notebook..."
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
                disabled={submitting}
              >
                {dt.cancel}
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={!selectedId || submitting}
              >
                {submitting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <BookPlus className="mr-2 h-4 w-4" />
                )}
                {submitting ? dt.adding : dt.add}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
