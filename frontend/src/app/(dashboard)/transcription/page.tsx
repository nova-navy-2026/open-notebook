"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  AudioLines,
  Captions,
  Copy,
  Download,
  Languages,
  Loader2,
  Sparkles,
  Upload,
  Users,
  X,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTranscriptionStore } from "@/lib/stores/transcription-store";
import { useTranslation } from "@/lib/hooks/use-translation";
import { PageInfoButton } from "@/components/common/PageInfoButton";
import { SaveTranscriptToNotebook } from "@/components/transcription/SaveTranscriptToNotebook";
import { transcriptionApi } from "@/lib/api/transcription";

// Stable colour palette for speaker badges (Tailwind classes).
const SPEAKER_PALETTE = [
  "bg-blue-100 text-blue-900 dark:bg-blue-900/40 dark:text-blue-100",
  "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100",
  "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100",
  "bg-rose-100 text-rose-900 dark:bg-rose-900/40 dark:text-rose-100",
  "bg-violet-100 text-violet-900 dark:bg-violet-900/40 dark:text-violet-100",
  "bg-cyan-100 text-cyan-900 dark:bg-cyan-900/40 dark:text-cyan-100",
];

function speakerColour(
  speaker: string | null | undefined,
  speakers: string[],
): string {
  if (!speaker) return "bg-muted text-foreground";
  const idx = Math.max(0, speakers.indexOf(speaker));
  return SPEAKER_PALETTE[idx % SPEAKER_PALETTE.length];
}

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return "00:00";
  const total = Math.round(sec);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function TranscriptionPage() {
  const { t, language: appLanguage } = useTranslation();
  const tp = t.transcriptionPage;

  const audio = useTranscriptionStore((s) => s.audio);
  const audioPreview = useTranscriptionStore((s) => s.audioPreview);
  const language = useTranscriptionStore((s) => s.language);
  const diarize = useTranscriptionStore((s) => s.diarize);
  const numSpeakers = useTranscriptionStore((s) => s.numSpeakers);
  const isLoading = useTranscriptionStore((s) => s.isLoading);
  const result = useTranscriptionStore((s) => s.result);
  const error = useTranscriptionStore((s) => s.error);
  const capabilities = useTranscriptionStore((s) => s.capabilities);
  const setAudio = useTranscriptionStore((s) => s.setAudio);
  const setLanguage = useTranscriptionStore((s) => s.setLanguage);
  const setDiarize = useTranscriptionStore((s) => s.setDiarize);
  const setNumSpeakers = useTranscriptionStore((s) => s.setNumSpeakers);
  const setError = useTranscriptionStore((s) => s.setError);
  const submit = useTranscriptionStore((s) => s.submit);
  const clear = useTranscriptionStore((s) => s.clear);
  const fetchCapabilities = useTranscriptionStore((s) => s.fetchCapabilities);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  // User-chosen title + report style for the document generated from the transcript.
  const [reportTitle, setReportTitle] = useState("");
  const [reportType, setReportType] = useState<
    "ata" | "conversation" | "summary" | "literal"
  >("summary");
  const router = useRouter();

  // Translation state
  const [translateTarget, setTranslateTarget] = useState("en");
  const [isTranslating, setIsTranslating] = useState(false);
  const [translatedText, setTranslatedText] = useState<string | null>(null);
  const [translateError, setTranslateError] = useState<string | null>(null);

  // Send the current transcript to the Research page so the user can
  // produce a Deep Research report from it (and then save the report
  // into a notebook just like any other research job).
  const sendToResearch = useCallback(() => {
    if (!result) return;
    // Prefer the diarized dialog if present — it carries speaker labels
    // and is more useful as research input than the flat transcript.
    const draft = (
      result.dialog && result.dialog.trim().length > 0
        ? result.dialog
        : result.text || ""
    ).trim();
    if (!draft) return;
    try {
      sessionStorage.setItem(
        "researchDraftFromTranscript",
        JSON.stringify({
          query: draft,
          source: "transcription",
          createdAt: Date.now(),
          // User choices: free title + report style + the app language so the
          // generated document is written/translated in the user's language.
          title: reportTitle.trim() || undefined,
          reportType,
          appLanguage,
        }),
      );
    } catch {
      // sessionStorage may be unavailable (private mode); silently skip.
    }
    router.push("/research?fromTranscript=1");
  }, [result, router, reportTitle, reportType, appLanguage]);

  const handleTranslate = useCallback(async () => {
    if (!result) return;
    const textToTranslate = (
      result.dialog && result.dialog.trim().length > 0
        ? result.dialog
        : result.text || ""
    ).trim();
    if (!textToTranslate) return;

    const languageName = translateTarget === "pt" ? "European Portuguese (pt-PT)" : "English";
    setIsTranslating(true);
    setTranslateError(null);
    setTranslatedText(null);
    try {
      const res = await transcriptionApi.translate(textToTranslate, languageName);
      setTranslatedText(res.translated_text);
    } catch (e) {
      setTranslateError(
        e instanceof Error ? e.message : (tp.translateError ?? "Translation failed."),
      );
    } finally {
      setIsTranslating(false);
    }
  }, [result, translateTarget, tp.translateError]);

  useEffect(() => {
    fetchCapabilities();
  }, [fetchCapabilities]);

  const acceptAttr = useMemo(() => {
    if (capabilities?.allowed_extensions?.length) {
      return capabilities.allowed_extensions.join(",");
    }
    return "audio/*,video/mp4,video/webm";
  }, [capabilities]);

  const diarizationDisabled = capabilities?.diarization_available === false;

  const handleFileSelect = useCallback(
    (file: File) => {
      const lower = file.name.toLowerCase();
      const okByMime =
        file.type.startsWith("audio/") || file.type.startsWith("video/");
      const okByExt = capabilities?.allowed_extensions?.some((ext) =>
        lower.endsWith(ext),
      );
      if (!okByMime && !okByExt) {
        setError(tp.invalidFile);
        return;
      }
      setAudio(file);
    },
    [capabilities, setAudio, setError, tp.invalidFile],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFileSelect(file);
    },
    [handleFileSelect],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submit();
  };

  const clearAll = () => {
    clear();
    if (fileInputRef.current) fileInputRef.current.value = "";
    setTranslatedText(null);
    setTranslateError(null);
  };

  const copyText = async (text: string | null | undefined) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* noop */
    }
  };

  const downloadText = (text: string | null | undefined, suffix: string) => {
    if (!text) return;
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `transcript_${Date.now()}${suffix}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="app-page space-y-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h1 className="text-3xl font-bold tracking-tight">{tp.title}</h1>
          <PageInfoButton pageKey="transcription" />
        </div>
        <p className="text-muted-foreground">{tp.subtitle}</p>
      </div>

      {diarizationDisabled && (
        <Alert>
          <AlertDescription>
            {tp.diarizationUnavailable}
            {capabilities?.diarization_unavailable_reason
              ? ` (${capabilities.diarization_unavailable_reason})`
              : null}
          </AlertDescription>
        </Alert>
      )}

      <form onSubmit={handleSubmit} className="app-form space-y-6">
        {/* Audio Upload */}
        <div className="space-y-2">
          <Label>{tp.uploadLabel}</Label>
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => fileInputRef.current?.click()}
            className={`relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
              isDragging
                ? "border-primary bg-primary/5"
                : audioPreview
                  ? "border-border bg-muted/50"
                  : "border-border hover:border-primary hover:bg-muted/50"
            }`}
          >
            {audioPreview ? (
              <div className="space-y-3">
                <AudioLines className="h-10 w-10 text-muted-foreground mx-auto" />
                <p className="text-foreground font-medium truncate max-w-md mx-auto">
                  {audio?.name ?? "audio"}
                </p>
                <audio
                  src={audioPreview}
                  controls
                  className="w-full max-w-md mx-auto"
                  onClick={(e) => e.stopPropagation()}
                />
                <p className="text-sm text-muted-foreground">
                  {tp.replaceHint}
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <Upload className="h-12 w-12 text-muted-foreground mx-auto" />
                <p className="text-foreground font-medium">{tp.dropHint}</p>
                <p className="text-sm text-muted-foreground">{tp.formats}</p>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={acceptAttr}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileSelect(file);
              }}
              className="hidden"
            />
          </div>
        </div>

        {/* Language */}
        <div className="space-y-2">
          <Label htmlFor="language">
            {tp.languageLabel}{" "}
            <span className="text-muted-foreground text-xs">{tp.optional}</span>
          </Label>
          <Select
            value={language || "auto"}
            onValueChange={(v) => setLanguage(v === "auto" ? "" : v)}
          >
            <SelectTrigger id="language">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">{tp.languageAuto}</SelectItem>
              <SelectItem value="pt">{tp.languagePortuguese}</SelectItem>
              <SelectItem value="en">{tp.languageEnglish}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Diarization */}
        <div className="space-y-3 rounded-lg border border-border p-4">
          <div className="flex items-start gap-3">
            <Checkbox
              id="diarize"
              checked={diarize}
              disabled={diarizationDisabled}
              onCheckedChange={(v) => setDiarize(Boolean(v))}
            />
            <div className="space-y-1 flex-1">
              <Label
                htmlFor="diarize"
                className={`cursor-pointer ${diarizationDisabled ? "text-muted-foreground" : ""}`}
              >
                {tp.diarizeLabel}
              </Label>
              <p className="text-xs text-muted-foreground">{tp.diarizeHint}</p>
            </div>
          </div>

          {diarize && !diarizationDisabled && (
            <div className="pl-7 space-y-2">
              <Label htmlFor="numSpeakers" className="text-xs">
                {tp.numSpeakersLabel}{" "}
                <span className="text-muted-foreground">{tp.optional}</span>
              </Label>
              <Input
                id="numSpeakers"
                type="number"
                min={1}
                max={20}
                value={numSpeakers}
                onChange={(e) => setNumSpeakers(e.target.value)}
                placeholder={tp.numSpeakersPlaceholder}
                className="max-w-[8rem]"
              />
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Actions */}
        <div className="flex gap-3">
          <Button type="submit" disabled={isLoading || !audio}>
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                {tp.transcribing}
              </>
            ) : (
              <>
                <Captions className="h-4 w-4 mr-2" />
                {tp.transcribe}
              </>
            )}
          </Button>
          <Button type="button" variant="outline" onClick={clearAll}>
            <X className="h-4 w-4 mr-2" />
            {tp.clear}
          </Button>
        </div>
      </form>

      {/* Results */}
      {result && (
        <div className="app-section space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="text-xl font-semibold tracking-tight">
              {tp.results}
            </h2>
            {result.diarized && result.speakers.length > 0 && (
              <Badge variant="secondary" className="gap-1">
                <Users className="h-3 w-3" />
                {tp.speakersDetected.replace(
                  "{count}",
                  String(result.speakers.length),
                )}
              </Badge>
            )}
            {result.language && (
              <Badge variant="outline">{result.language}</Badge>
            )}
          </div>

          {/* Generate a document from the transcript: free title + report style */}
          <Card>
            <CardContent className="flex flex-col gap-3 pt-4 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-1">
                <Label htmlFor="report-title" className="text-xs text-muted-foreground">
                  {tp.reportTitleLabel ?? "Título do documento"}
                </Label>
                <Input
                  id="report-title"
                  value={reportTitle}
                  onChange={(e) => setReportTitle(e.target.value)}
                  placeholder={tp.reportTitlePlaceholder ?? "Ex.: Reunião de equipa 19/06"}
                />
              </div>
              <div className="space-y-1 sm:w-56">
                <Label className="text-xs text-muted-foreground">
                  {tp.reportTypeLabel ?? "Tipo de documento"}
                </Label>
                <Select
                  value={reportType}
                  onValueChange={(v) =>
                    setReportType(v as "ata" | "conversation" | "summary" | "literal")
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="summary">{tp.reportTypeSummary ?? "Resumo de reunião"}</SelectItem>
                    <SelectItem value="ata">{tp.reportTypeAta ?? "ATA de reunião"}</SelectItem>
                    <SelectItem value="conversation">{tp.reportTypeConversation ?? "Conversa / Diálogo"}</SelectItem>
                    <SelectItem value="literal">{tp.reportTypeLiteral ?? "Transcrição literal"}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                type="button"
                variant="default"
                onClick={sendToResearch}
                disabled={!result.text && !result.dialog}
                title={tp.generateDocumentHint ?? "Gerar documento a partir da transcrição"}
              >
                <Sparkles className="h-4 w-4 mr-2" />
                {tp.generateDocument ?? "Gerar documento"}
              </Button>
            </CardContent>
          </Card>

          {/* Full text */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {tp.fullTranscript}
              </CardTitle>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => copyText(result.text)}
                  title={tp.copy}
                >
                  <Copy className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => downloadText(result.text, "")}
                  title={tp.download}
                >
                  <Download className="h-4 w-4" />
                </Button>
                <SaveTranscriptToNotebook
                  content={result.text || ""}
                  defaultTitle={reportTitle.trim() || tp.defaultNoteTitle}
                  disabled={!result.text}
                />
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {result.text || tp.emptyTranscript}
              </p>

              {/* Translate — inline below the transcript */}
              <div className="border-t pt-4 flex flex-col gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <Languages className="h-4 w-4 text-muted-foreground shrink-0" />
                  <Select value={translateTarget} onValueChange={setTranslateTarget}>
                    <SelectTrigger className="w-36 h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="en">{tp.languageEnglish}</SelectItem>
                      <SelectItem value="pt">{tp.languagePortuguese}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleTranslate}
                    disabled={isTranslating || (!result.text && !result.dialog)}
                  >
                    {isTranslating && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                    {isTranslating ? (tp.translating ?? "Translating…") : (tp.translate ?? "Translate")}
                  </Button>
                </div>
                {translateError && (
                  <Alert variant="destructive">
                    <AlertDescription>{translateError}</AlertDescription>
                  </Alert>
                )}
                {translatedText && (
                  <div className="border rounded-lg p-3 bg-muted/30">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-xs text-muted-foreground font-medium">
                        {tp.translationResult ?? "Translation"}
                      </span>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => copyText(translatedText)}
                          title={tp.copy}
                        >
                          <Copy className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => downloadText(translatedText, "_translated")}
                          title={tp.download}
                        >
                          <Download className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">
                      {translatedText}
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Diarized dialog */}
          {result.diarized && result.dialog && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {tp.dialog}
                </CardTitle>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => copyText(result.dialog ?? "")}
                    title={tp.copy}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => downloadText(result.dialog ?? "", "_dialog")}
                    title={tp.download}
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans">
                  {result.dialog}
                </pre>
              </CardContent>
            </Card>
          )}

          {/* Timeline */}
          {result.segments.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {tp.timeline}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {result.segments.map((seg, idx) => (
                    <div
                      key={`${seg.start}-${idx}`}
                      className="flex gap-3 items-start text-sm"
                    >
                      <span className="font-mono text-xs text-muted-foreground shrink-0 w-24 pt-0.5">
                        {formatTime(seg.start)} – {formatTime(seg.end)}
                      </span>
                      {seg.speaker && (
                        <span
                          className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${speakerColour(seg.speaker, result.speakers)}`}
                        >
                          {seg.speaker}
                        </span>
                      )}
                      <span className="leading-relaxed">{seg.text}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}
      </div>
    </div>
  );
}
