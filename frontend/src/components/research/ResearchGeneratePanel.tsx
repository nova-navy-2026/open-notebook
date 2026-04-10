"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Loader2, Search, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  useReportTypes,
  useResearchTones,
  useGenerateResearch,
} from "@/lib/hooks/use-research";
import { useTranslation } from "@/lib/hooks/use-translation";
import { ModelSelector } from "@/components/common/ModelSelector";
import { useModelDefaults } from "@/lib/hooks/use-models";

interface ResearchGeneratePanelProps {
  onJobStarted?: () => void;
}

export function ResearchGeneratePanel({
  onJobStarted,
}: ResearchGeneratePanelProps) {
  const { t } = useTranslation();
  const { data: reportTypes, isLoading: typesLoading } = useReportTypes();
  const { data: tones, isLoading: tonesLoading } = useResearchTones();
  const generateMutation = useGenerateResearch();
  const { data: modelDefaults } = useModelDefaults();

  const [query, setQuery] = useState("");
  const [reportType, setReportType] = useState("research_report");
  const [tone, setTone] = useState("Objective");
  const [modelId, setModelId] = useState("");

  // Pre-select the default chat model once loaded
  useEffect(() => {
    if (!modelId && modelDefaults?.default_chat_model) {
      setModelId(modelDefaults.default_chat_model);
    }
  }, [modelDefaults?.default_chat_model]);

  const isLoading = typesLoading || tonesLoading;
  const isSubmitting = generateMutation.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    await generateMutation.mutateAsync({
      query: query.trim(),
      report_type: reportType,
      report_source: "local",
      tone,
      source_urls: [],
      model_id: modelId || undefined,
      use_amalia: !!modelId,
      run_in_background: true,
    });

    onJobStarted?.();
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Research Query */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            {t.research?.queryTitle ?? "Research Query"}
          </CardTitle>
          <CardDescription>
            {t.research?.queryDescription ??
              "Enter your research question or topic. Be specific for better results."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              t.research?.queryPlaceholder ??
              "e.g., What are the latest developments in maritime autonomous systems?"
            }
            className="min-h-[100px] text-base"
            disabled={isSubmitting}
          />
        </CardContent>
      </Card>

      {/* Report Configuration */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Report Type */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t.research?.reportType ?? "Report Type"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Select
              value={reportType}
              onValueChange={setReportType}
              disabled={isSubmitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {reportTypes?.map((rt) => (
                  <SelectItem key={rt.value} value={rt.value}>
                    {rt.label}
                    {rt.speed ? ` (${rt.speed})` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {reportTypes?.find((rt) => rt.value === reportType)
                ?.description ?? ""}
              {" - "}
              {reportTypes?.find((rt) => rt.value === reportType)?.speed ?? ""}
            </p>
          </CardContent>
        </Card>

        {/* Tone */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t.research?.toneLabel ?? "Writing Tone"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Select
              value={tone}
              onValueChange={setTone}
              disabled={isSubmitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {tones?.map((tn) => (
                  <SelectItem key={tn.value} value={tn.value}>
                    {tn.label} — {tn.description}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>

        {/* Model Selection */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              {t.research?.modelLabel ?? "AI Model"}
            </CardTitle>
            <CardDescription>
              Select the language model to use for generating the report.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ModelSelector
              modelType="language"
              value={modelId}
              onChange={setModelId}
              placeholder="Select a model..."
              disabled={isSubmitting}
            />
          </CardContent>
        </Card>
      </div>

      {/* Submit */}
      <div className="flex justify-end">
        <Button
          type="submit"
          size="lg"
          disabled={!query.trim() || isSubmitting || isLoading}
          className="min-w-[200px]"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {t.research?.generating ?? "Generating..."}
            </>
          ) : (
            <>
              <Search className="mr-2 h-4 w-4" />
              {t.research?.generate ?? "Generate Research"}
            </>
          )}
        </Button>
      </div>
    </form>
  );
}
