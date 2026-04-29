"use client";

import { useRef, useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Video, Upload, Loader2, X, Download } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { useVideoTrackingStore } from "@/lib/stores/vision-store";
import { useTranslation } from "@/lib/hooks/use-translation";
import { AddToNotebookDropdown } from "@/components/vision/AddToNotebookDropdown";

export default function VideoTrackingPage() {
  const { t } = useTranslation();
  const tp = t.videoTrackingPage;
  // Persist state across tab switches: state lives in the zustand store
  // so that an in-flight tracking job keeps running in the background and
  // the inputs / results survive unmounting this page.
  const video = useVideoTrackingStore((s) => s.video);
  const videoPreview = useVideoTrackingStore((s) => s.videoPreview);
  const target = useVideoTrackingStore((s) => s.target);
  const engine = useVideoTrackingStore((s) => s.engine);
  const isLoading = useVideoTrackingStore((s) => s.isLoading);
  const resultVideo = useVideoTrackingStore((s) => s.resultVideo);
  const resultText = useVideoTrackingStore((s) => s.resultText);
  const error = useVideoTrackingStore((s) => s.error);
  const setVideo = useVideoTrackingStore((s) => s.setVideo);
  const setTarget = useVideoTrackingStore((s) => s.setTarget);
  const setEngine = useVideoTrackingStore((s) => s.setEngine);
  const setError = useVideoTrackingStore((s) => s.setError);
  const submit = useVideoTrackingStore((s) => s.submit);
  const clear = useVideoTrackingStore((s) => s.clear);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleVideoSelect = (file: File) => {
    if (!file.type.startsWith("video/")) {
      setError(tp.invalidFile);
      return;
    }
    setVideo(file);
  };

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleVideoSelect(file);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
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
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto px-4 md:px-6 py-6 space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">{tp.title}</h1>
        <p className="text-muted-foreground">
          {tp.subtitle}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6 max-w-4xl">
        {/* Video Upload */}
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
                : videoPreview
                  ? "border-border bg-muted/50"
                  : "border-border hover:border-primary hover:bg-muted/50"
            }`}
          >
            {videoPreview ? (
              <div className="relative">
                <video
                  src={videoPreview}
                  className="max-h-64 mx-auto rounded-lg"
                  muted
                  playsInline
                  onMouseEnter={(e) =>
                    (e.target as HTMLVideoElement).play().catch(() => {})
                  }
                  onMouseLeave={(e) => {
                    const v = e.target as HTMLVideoElement;
                    v.pause();
                    v.currentTime = 0;
                  }}
                />
                <p className="text-sm text-muted-foreground mt-2">
                  {tp.replaceHint}
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <Upload className="h-12 w-12 text-muted-foreground mx-auto" />
                <p className="text-foreground font-medium">
                  {tp.dropHint}
                </p>
                <p className="text-sm text-muted-foreground">
                  {tp.formats}
                </p>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleVideoSelect(file);
              }}
              className="hidden"
            />
          </div>
        </div>

        {/* Target Input */}
        <div className="space-y-2">
          <Label htmlFor="target">
            {tp.targetLabel}{" "}
            {engine === "sam3" ? (
              <span className="text-destructive">*</span>
            ) : (
              <span className="text-muted-foreground text-xs">{t.imageAnalysisPage.optional}</span>
            )}
          </Label>
          <Input
            id="target"
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder={
              engine === "sam3"
                ? tp.targetPlaceholder
                : t.imageAnalysisPage.queryPlaceholderRfdetr
            }
            required={engine === "sam3"}
          />
        </div>

        {/* Engine Selector */}
        <div className="space-y-2">
          <Label htmlFor="engine">{tp.engineLabel}</Label>
          <select
            id="engine"
            value={engine}
            onChange={(e) => setEngine(e.target.value as "sam3" | "rfdetr")}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <option value="sam3">{t.imageAnalysisPage.engineSam3}</option>
            <option value="rfdetr">{t.imageAnalysisPage.engineRfdetr}</option>
          </select>
          <p className="text-xs text-muted-foreground">
            {engine === "sam3"
              ? t.imageAnalysisPage.engineHintSam3
              : t.imageAnalysisPage.engineHintRfdetr}
          </p>
        </div>

        {/* Error */}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Actions */}
        <div className="flex gap-3">
          <Button
            type="submit"
            disabled={isLoading || !video || (engine === "sam3" && !target.trim())}
          >
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                {tp.processing}
              </>
            ) : (
              <>
                <Video className="h-4 w-4 mr-2" />
                {tp.process}
              </>
            )}
          </Button>
          <Button type="button" variant="outline" onClick={clearAll}>
            <X className="h-4 w-4 mr-2" />
            {tp.clear}
          </Button>
        </div>
      </form>

      {/* Progress indicator */}
      {isLoading && (
        <Card className="max-w-4xl">
          <CardContent className="flex items-center gap-4 py-6">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <div>
              <p className="font-medium">{tp.processingTitle}</p>
              <p className="text-sm text-muted-foreground">
                {tp.processingDesc.replace("{target}", target)}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Result */}
      {(resultVideo || resultText) && !isLoading && (
        <div className="space-y-4 max-w-4xl">
          <h2 className="text-xl font-semibold tracking-tight">{tp.result}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {resultVideo && (
              <Card>
                <CardHeader className="flex flex-row items-center justify-between gap-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {tp.trackedVideo}
                  </CardTitle>
                  <div className="flex items-center gap-1">
                    <AddToNotebookDropdown
                      mediaKind="video"
                      mediaDataUrl={resultVideo}
                      analysisText={resultText}
                      title={
                        target?.trim()
                          ? `Análise de Vídeo: ${target.trim()}`
                          : "Análise de Vídeo"
                      }
                    />
                    <Button variant="ghost" size="sm" asChild>
                      <a href={resultVideo} download="tracked_video.mp4">
                        <Download className="h-4 w-4 mr-1" />
                        {tp.download}
                      </a>
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  <video
                    src={resultVideo}
                    controls
                    className="w-full rounded-lg"
                    autoPlay
                    muted
                  />
                </CardContent>
              </Card>
            )}
            {resultText && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {tp.summary}
                  </CardTitle>
                </CardHeader>
                <CardContent className="prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {resultText}
                  </ReactMarkdown>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

    </div>
  );
}
