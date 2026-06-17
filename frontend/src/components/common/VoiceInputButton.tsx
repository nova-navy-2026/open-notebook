"use client";

import { useCallback } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/hooks/use-translation";
import {
  useVoiceRecorder,
  type VoiceRecorderError,
} from "@/lib/hooks/use-voice-recorder";

interface VoiceInputButtonProps {
  /** Receives the transcribed text so the caller can insert it into the prompt. */
  onTranscript: (text: string) => void;
  disabled?: boolean;
  language?: string;
  surface?: "global_chat" | "notebook_chat";
  notebookId?: string;
  className?: string;
}

/**
 * Microphone button that dictates into a prompt box. Click to start listening;
 * it auto-stops a moment after you stop talking (or click again to stop now),
 * then transcribes the clip and hands the text back via `onTranscript`.
 */
export function VoiceInputButton({
  onTranscript,
  disabled,
  language,
  surface,
  notebookId,
  className,
}: VoiceInputButtonProps) {
  const { t } = useTranslation();

  const handleError = useCallback(
    (error: VoiceRecorderError) => {
      switch (error) {
        case "permission-denied":
          toast.error(t.chat.voicePermissionDenied);
          break;
        case "unsupported":
          toast.error(t.chat.voiceUnsupported);
          break;
        case "no-speech":
        case "empty-transcript":
          toast.info(t.chat.voiceNoSpeech);
          break;
        case "transcription-failed":
          toast.error(t.chat.voiceFailed);
          break;
      }
    },
    [t],
  );

  const { status, level, toggle } = useVoiceRecorder({
    onTranscript,
    onError: handleError,
    language,
    surface,
    notebookId,
  });

  const listening = status === "listening";
  const busy = status === "requesting" || status === "transcribing";

  const title = listening
    ? t.chat.voiceStop
    : status === "transcribing"
      ? t.chat.voiceTranscribing
      : status === "requesting"
        ? t.chat.voiceListening
        : t.chat.voiceInput;

  return (
    <Button
      type="button"
      variant={listening ? "destructive" : "outline"}
      size="icon"
      className={cn("relative h-[40px] w-[40px] flex-shrink-0", className)}
      onClick={toggle}
      disabled={disabled || busy}
      title={title}
      aria-label={title}
    >
      {busy ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : listening ? (
        <>
          <span
            className="absolute inset-0 rounded-md bg-destructive/40 animate-ping"
            style={{ opacity: 0.35 + level * 0.5 }}
          />
          <Square className="relative h-3.5 w-3.5 fill-current" />
        </>
      ) : (
        <Mic className="h-4 w-4" />
      )}
    </Button>
  );
}
