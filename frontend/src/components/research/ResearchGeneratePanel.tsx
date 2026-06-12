"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
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
import {
  useReportTypes,
  useResearchTones,
  useGenerateResearch,
} from "@/lib/hooks/use-research";
import { useTranslation } from "@/lib/hooks/use-translation";
import { ModelSelector } from "@/components/common/ModelSelector";
import { useModelDefaults } from "@/lib/hooks/use-models";
import type { ReportTypeInfo, ToneInfo } from "@/lib/types/research";

const EMPTY_REPORT_TYPES: ReportTypeInfo[] = [];
const EMPTY_TONES: ToneInfo[] = [];

// Map an i18n locale code to a human-readable language name the backend
// prompt can embed (e.g. "Write the minutes in {language}").
function toLanguageName(locale: string): string {
  switch (locale) {
    case "pt-PT":
      return "português europeu (pt-PT)";
    case "en-US":
      return "English";
    case "it-IT":
      return "italiano (it-IT)";
    case "zh-TW":
      return "繁體中文 (zh-TW)";
    default:
      return locale;
  }
}

interface ResearchGeneratePanelProps {
  onJobStarted?: () => void;
}

export function ResearchGeneratePanel({
  onJobStarted,
}: ResearchGeneratePanelProps) {
  const { t, language } = useTranslation();
  const { data: reportTypes, isLoading: typesLoading } = useReportTypes();
  const { data: tones, isLoading: tonesLoading } = useResearchTones();
  const generateMutation = useGenerateResearch();
  const { data: modelDefaults } = useModelDefaults();

  const [query, setQuery] = useState("");
  const [reportType, setReportType] = useState("research_report");
  const [tone, setTone] = useState("Objective");
  const [modelId, setModelId] = useState("");
  const [fromTranscript, setFromTranscript] = useState(false);

  const availableReportTypes = reportTypes ?? EMPTY_REPORT_TYPES;
  const availableTones = tones ?? EMPTY_TONES;
  const selectedReportTypeInfo = useMemo(
    () =>
      availableReportTypes.find((rt) => rt.value === reportType) ??
      availableReportTypes[0],
    [availableReportTypes, reportType],
  );
  const selectedToneInfo = useMemo(
    () => availableTones.find((tn) => tn.value === tone) ?? availableTones[0],
    [availableTones, tone],
  );
  const selectedReportTypeValue = selectedReportTypeInfo?.value ?? "";
  const selectedToneValue = selectedToneInfo?.value ?? "";

  const handleReportTypeChange = useCallback((value: string) => {
    setReportType((current) => (current === value ? current : value));
  }, []);

  const handleToneChange = useCallback((value: string) => {
    setTone((current) => (current === value ? current : value));
  }, []);

  const handleModelChange = useCallback((value: string) => {
    setModelId((current) => (current === value ? current : value));
  }, []);

  // Pre-fill the query when arriving from the Transcription page.
  // The transcript text is stashed in sessionStorage by that page so
  // we don't have to plumb a global store for a one-shot hand-off.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = sessionStorage.getItem("researchDraftFromTranscript");
      if (!raw) return;
      const parsed = JSON.parse(raw) as { query?: string; source?: string };
      if (parsed?.query && parsed.query.trim().length > 0) {
        // Use the raw transcript as-is. The dedicated meeting-minutes (ATA)
        // backend path summarises it directly with a specialised prompt and
        // does NOT run any OpenSearch / web retrieval, so there's no need to
        // wrap it with research instructions here.
        setQuery(parsed.query.trim());
        setFromTranscript(true);
      }
      // Consume the draft so a manual refresh doesn't re-apply it.
      sessionStorage.removeItem("researchDraftFromTranscript");
    } catch {
      // Ignore malformed payloads.
    }
  }, []);

  // Pre-select the default chat model once loaded
  useEffect(() => {
    if (!modelId && modelDefaults?.default_chat_model) {
      setModelId(modelDefaults.default_chat_model);
    }
  }, [modelDefaults?.default_chat_model, modelId]);

  const isLoading = typesLoading || tonesLoading;
  const isSubmitting = generateMutation.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !selectedReportTypeValue || !selectedToneValue) return;

    await generateMutation.mutateAsync({
      query: query.trim(),
      // A meeting transcript is turned into structured minutes (ATA) via a
      // dedicated, retrieval-free backend path. Otherwise honour the
      // selected report type.
      report_type: fromTranscript ? "meeting_minutes" : selectedReportTypeValue,
      report_source: "local",
      tone: selectedToneValue,
      source_urls: [],
      model_id: modelId || undefined,
      // Meeting minutes never touch OpenSearch (the report type forces a
      // retrieval-free path), so keep the AMALIA writer for quality output.
      use_amalia: true,
      // Write the minutes in the active conversation language.
      language: fromTranscript ? toLanguageName(language) : undefined,
      run_in_background: true,
    });

    onJobStarted?.();
  };

  return (
    <form onSubmit={handleSubmit} className="app-form space-y-6">
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
          {fromTranscript && (
            <div className="mb-3 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
              {t.research?.transcriptAtaNotice ??
                "Pre-filled from the latest transcription. A meeting-minutes (ATA) document will be generated directly from the transcript in the conversation language — no OpenSearch context is used. Edit before generating if needed."}
            </div>
          )}
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
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {/* Report Type */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t.research?.reportType ?? "Report Type"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Select
              value={selectedReportTypeValue}
              onValueChange={handleReportTypeChange}
              disabled={isSubmitting || availableReportTypes.length === 0}
            >
              <SelectTrigger>
                <SelectValue placeholder={t.research?.reportType ?? "Report Type"} />
              </SelectTrigger>
              <SelectContent>
                {availableReportTypes.map((rt) => (
                  <SelectItem key={rt.value} value={rt.value}>
                    {rt.label}
                    {rt.speed ? ` (${rt.speed})` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {selectedReportTypeInfo?.description ?? ""}
              {" - "}
              {selectedReportTypeInfo?.speed ?? ""}
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
              value={selectedToneValue}
              onValueChange={handleToneChange}
              disabled={isSubmitting || availableTones.length === 0}
            >
              <SelectTrigger>
                <SelectValue placeholder={t.research?.toneLabel ?? "Writing Tone"} />
              </SelectTrigger>
              <SelectContent>
                {availableTones.map((tn) => (
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
              {t.research?.modelLabelDesc ??
                "Select the language model to use for generating the report."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ModelSelector
              modelType="language"
              value={modelId}
              onChange={handleModelChange}
              placeholder={
                t.research?.selectModelPlaceholder ?? "Select a model..."
              }
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
          disabled={
            !query.trim() ||
            isSubmitting ||
            isLoading ||
            !selectedReportTypeValue ||
            !selectedToneValue
          }
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
