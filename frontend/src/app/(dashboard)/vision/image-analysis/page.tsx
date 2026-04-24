"use client";

import { useState, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getApiUrl } from "@/lib/config";
import { useAuthStore } from "@/lib/stores/auth-store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Image as ImageIcon, Upload, Loader2, X, Download } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function ImageAnalysisPage() {
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [engine, setEngine] = useState<"sam3" | "rfdetr">("sam3");
  const [isLoading, setIsLoading] = useState(false);
  const [resultText, setResultText] = useState<string | null>(null);
  const [resultImage, setResultImage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleImageSelect = (file: File) => {
    if (!file.type.startsWith("image/")) {
      setError("Please select a valid image file.");
      return;
    }
    setImage(file);
    setError(null);
    const reader = new FileReader();
    reader.onloadend = () => setImagePreview(reader.result as string);
    reader.readAsDataURL(file);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleImageSelect(file);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!image || !query.trim()) {
      setError("Please provide both an image and a query.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setResultText(null);
    setResultImage(null);

    try {
      const formData = new FormData();
      formData.append("image", image);
      formData.append("query", query);
      formData.append("engine", engine);

      const apiUrl = await getApiUrl();
      const token = useAuthStore.getState().token;
      const response = await fetch(`${apiUrl}/api/vision/image-analysis`, {
        method: "POST",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => null);
        throw new Error(err?.detail || `Server error (${response.status})`);
      }

      const data = await response.json();
      setResultText(data.text || null);
      setResultImage(data.image_base64 || imagePreview);
    } catch {
      setError("Failed to analyze image. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const clearAll = () => {
    setImage(null);
    setImagePreview(null);
    setQuery("");
    setResultText(null);
    setResultImage(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto px-4 md:px-6 py-6 space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">Image Analysis</h1>
        <p className="text-muted-foreground">
          Upload an image and ask a question about it. The model will analyze
          the image and return both a visual result and a text response.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6 max-w-4xl">
        {/* Image Upload */}
        <div className="space-y-2">
          <Label>Upload Image</Label>
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
                <img
                  src={imagePreview}
                  alt="Preview"
                  className="max-h-64 mx-auto rounded-lg"
                />
                <p className="text-sm text-muted-foreground mt-2">
                  Click or drag to replace
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <Upload className="h-12 w-12 text-muted-foreground mx-auto" />
                <p className="text-foreground font-medium">
                  Drop an image here or click to browse
                </p>
                <p className="text-sm text-muted-foreground">
                  PNG, JPG, JPEG, WEBP
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
            Query {engine === "sam3" ? <span className="text-destructive">*</span> : <span className="text-muted-foreground text-xs">(optional)</span>}
          </Label>
          <Input
            id="query"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              engine === "sam3"
                ? "e.g. red boat, person wearing a helmet, license plate..."
                : "Leave empty to detect everything, or type a COCO class (person, car, boat...) to filter"
            }
            required={engine === "sam3"}
          />
        </div>

        {/* Engine Selector */}
        <div className="space-y-2">
          <Label htmlFor="engine">Detection Engine</Label>
          <select
            id="engine"
            value={engine}
            onChange={(e) => setEngine(e.target.value as "sam3" | "rfdetr")}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <option value="sam3">SAM3 (open-vocabulary, high-quality)</option>
            <option value="rfdetr">RF-DETR (COCO classes, real-time)</option>
          </select>
          <p className="text-xs text-muted-foreground">
            {engine === "sam3"
              ? "Describe anything in natural language. Slower but more flexible."
              : "Detects COCO-80 classes (person, car, boat, dog...). Leave query blank to detect everything; type a class name to filter."}
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
          <Button type="submit" disabled={isLoading || !image || (engine === "sam3" && !query.trim())}>
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <ImageIcon className="h-4 w-4 mr-2" />
                Analyze Image
              </>
            )}
          </Button>
          <Button type="button" variant="outline" onClick={clearAll}>
            <X className="h-4 w-4 mr-2" />
            Clear
          </Button>
        </div>
      </form>

      {/* Results */}
      {(resultText || resultImage) && (
        <div className="space-y-4 max-w-4xl">
          <h2 className="text-xl font-semibold tracking-tight">Results</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {resultImage && (
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Output Image
                  </CardTitle>
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
                    Download
                  </Button>
                </CardHeader>
                <CardContent>
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
                    Analysis
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
