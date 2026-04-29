"use client";

import { useRef, useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Image as ImageIcon, Upload, Loader2, X, Download } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { useImageAnalysisStore } from "@/lib/stores/vision-store";
import { useTranslation } from "@/lib/hooks/use-translation";
import { AddToNotebookDropdown } from "@/components/vision/AddToNotebookDropdown";

export default function ImageAnalysisPage() {
  const { t } = useTranslation();
  const tp = t.imageAnalysisPage;
  // All long-lived state lives in the zustand store so that switching
  // tabs (or even unmounting this page) does not cancel an in-flight
  // analysis nor lose the inputs / results.
  const image = useImageAnalysisStore((s) => s.image);
  const imagePreview = useImageAnalysisStore((s) => s.imagePreview);
  const query = useImageAnalysisStore((s) => s.query);
  const engine = useImageAnalysisStore((s) => s.engine);
  const isLoading = useImageAnalysisStore((s) => s.isLoading);
  const resultText = useImageAnalysisStore((s) => s.resultText);
  const resultImage = useImageAnalysisStore((s) => s.resultImage);
  const error = useImageAnalysisStore((s) => s.error);
  const setImage = useImageAnalysisStore((s) => s.setImage);
  const setQuery = useImageAnalysisStore((s) => s.setQuery);
  const setEngine = useImageAnalysisStore((s) => s.setEngine);
  const setError = useImageAnalysisStore((s) => s.setError);
  const submit = useImageAnalysisStore((s) => s.submit);
  const clear = useImageAnalysisStore((s) => s.clear);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleImageSelect = (file: File) => {
    if (!file.type.startsWith("image/")) {
      setError(tp.invalidFile);
      return;
    }
    setImage(file);
  };

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleImageSelect(file);
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
        {/* Image Upload */}
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
                : imagePreview
                  ? "border-border bg-muted/50"
                  : "border-border hover:border-primary hover:bg-muted/50"
            }`}
          >
            {imagePreview ? (
              <div className="relative">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={imagePreview}
                  alt="Preview"
                  className="max-h-64 mx-auto rounded-lg"
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
              accept="image/*"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleImageSelect(file);
              }}
              className="hidden"
            />
          </div>
        </div>

        {/* Query Input */}
        <div className="space-y-2">
          <Label htmlFor="query">
            {tp.queryLabel}{" "}
            {engine === "sam3" ? (
              <span className="text-destructive">*</span>
            ) : (
              <span className="text-muted-foreground text-xs">{tp.optional}</span>
            )}
          </Label>
          <Input
            id="query"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              engine === "sam3"
                ? tp.queryPlaceholderSam3
                : tp.queryPlaceholderRfdetr
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
            <option value="sam3">{tp.engineSam3}</option>
            <option value="rfdetr">{tp.engineRfdetr}</option>
          </select>
          <p className="text-xs text-muted-foreground">
            {engine === "sam3" ? tp.engineHintSam3 : tp.engineHintRfdetr}
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
            disabled={isLoading || !image || (engine === "sam3" && !query.trim())}
          >
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                {tp.analyzing}
              </>
            ) : (
              <>
                <ImageIcon className="h-4 w-4 mr-2" />
                {tp.analyze}
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
      {(resultText || resultImage) && (
        <div className="space-y-4 max-w-4xl">
          <h2 className="text-xl font-semibold tracking-tight">{tp.results}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {resultImage && (
              <Card>
                <CardHeader className="flex flex-row items-center justify-between gap-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {tp.outputImage}
                  </CardTitle>
                  <div className="flex items-center gap-1">
                    <AddToNotebookDropdown
                      mediaKind="image"
                      mediaDataUrl={resultImage}
                      analysisText={resultText}
                      title={
                        query?.trim()
                          ? `Análise de Imagem: ${query.trim()}`
                          : "Análise de Imagem"
                      }
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        const link = document.createElement("a");
                        link.href = resultImage;
                        link.download = `analysis_${Date.now()}.png`;
                        link.click();
                      }}
                    >
                      <Download className="h-4 w-4 mr-1" />
                      {tp.download}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={resultImage}
                    alt="Analysis result"
                    className="w-full rounded-lg"
                  />
                </CardContent>
              </Card>
            )}
            {resultText && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {tp.analysis}
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
