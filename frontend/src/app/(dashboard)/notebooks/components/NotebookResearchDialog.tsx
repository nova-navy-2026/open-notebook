"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
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
import {
  Loader2,
  Search,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  useReportTypes,
  useResearchTones,
  useGenerateResearch,
  useResearchJob,
  useSaveResearchAsNote,
} from "@/lib/hooks/use-research";
import { useTranslation } from "@/lib/hooks/use-translation";
import { ModelSelector } from "@/components/common/ModelSelector";
import { useModelDefaults } from "@/lib/hooks/use-models";

interface NotebookResearchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  notebookId: string;
}

export function NotebookResearchDialog({
  open,
  onOpenChange,
  notebookId,
}: NotebookResearchDialogProps) {
  const { t } = useTranslation();

  // Form state
  const [query, setQuery] = useState("");
  const [reportType, setReportType] = useState("research_report");
  const [tone, setTone] = useState("Objective");
  const [modelId, setModelId] = useState("");

  // Job tracking
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [savedAsNote, setSavedAsNote] = useState(false);

  // Hooks
  const { data: reportTypes, isLoading: typesLoading } = useReportTypes();
  const { data: tones, isLoading: tonesLoading } = useResearchTones();
  const generateMutation = useGenerateResearch();
  const saveAsNoteMutation = useSaveResearchAsNote();
  const { data: activeJob } = useResearchJob(activeJobId);
  const { data: modelDefaults } = useModelDefaults();

  // Pre-select the default chat model once loaded
  useEffect(() => {
    if (!modelId && modelDefaults?.default_chat_model) {
      setModelId(modelDefaults.default_chat_model);
    }
  }, [modelDefaults?.default_chat_model]);

  // Auto-save as note when the job completes
  useEffect(() => {
    if (
      activeJob?.status === "completed" &&
      activeJob.has_result &&
      !savedAsNote &&
      !saveAsNoteMutation.isPending
    ) {
      setSavedAsNote(true);
      saveAsNoteMutation.mutate({
        research_id: activeJob.id,
        notebook_id: notebookId,
        title: `🔬 ${query.slice(0, 80)}`,
      });
    }
  }, [activeJob, savedAsNote, saveAsNoteMutation, notebookId, query]);

  // Reset state when dialog closes
  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        // Only allow closing if not mid-research
        if (
          activeJobId &&
          activeJob?.status !== "completed" &&
          activeJob?.status !== "failed"
        ) {
          // Research is running — keep dialog open but allow user to force-close
        }
        setQuery("");
        setReportType("research_report");
        setTone("Objective");
        setModelId("");
        setActiveJobId(null);
        setSavedAsNote(false);
      }
      onOpenChange(nextOpen);
    },
    [activeJobId, activeJob, onOpenChange],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    const result = await generateMutation.mutateAsync({
      query: query.trim(),
      report_type: reportType,
      report_source: "local",
      tone,
      source_urls: [],
      model_id: modelId || undefined,
      use_amalia: true, // Always fetch OpenSearch docs; backend routes LLM by model provider
      run_in_background: true,
      notebook_id: notebookId,
    });

    // Result has job_id when background mode
    if ("job_id" in result) {
      setActiveJobId(result.job_id);
    }
  };

  const isLoading = typesLoading || tonesLoading;
  const isSubmitting = generateMutation.isPending;
  const isRunning =
    activeJobId !== null &&
    activeJob?.status !== "completed" &&
    activeJob?.status !== "failed";
  const isCompleted = activeJob?.status === "completed";
  const isFailed = activeJob?.status === "failed";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="!max-w-4xl sm:!max-w-4xl w-[min(896px,calc(100vw-2rem))] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            {t.research?.title ?? "Research"}
          </DialogTitle>
          <DialogDescription>
            {t.research?.notebookResearchDesc ??
              "Run a deep research and automatically save the result as a note in this notebook."}
          </DialogDescription>
        </DialogHeader>

        {/* Show progress/status when a job is active */}
        {activeJobId ? (
          <div className="space-y-4 py-4">
            {/* Status indicator */}
            <div className="flex items-center gap-3 p-4 rounded-lg border bg-muted/30">
              {isRunning && (
                <>
                  <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
                  <div>
                    <p className="font-medium text-sm">
                      {t.research?.researchInProgress ??
                        "Research in progress..."}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {activeJob?.progress ||
                        (t.research?.pleaseWait ??
                          "Please wait, this may take a few minutes.")}
                    </p>
                  </div>
                </>
              )}
              {isCompleted && (
                <>
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                  <div>
                    <p className="font-medium text-sm">
                      {savedAsNote
                        ? (t.research?.savedAsNoteInNotebook ??
                          "Research complete — saved as note!")
                        : (t.research?.savingAsNote ??
                          "Research complete — saving as note...")}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t.research?.checkNotesColumn ??
                        "Check the Notes column to see the result."}
                    </p>
                  </div>
                </>
              )}
              {isFailed && (
                <>
                  <AlertCircle className="h-5 w-5 text-red-500" />
                  <div>
                    <p className="font-medium text-sm">
                      {t.research?.researchFailed ?? "Research failed"}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {activeJob?.error ||
                        (t.common?.error ?? "An error occurred.")}
                    </p>
                  </div>
                </>
              )}
            </div>

            {/* Query reminder */}
            <div className="p-3 rounded border bg-muted/10">
              <p className="text-xs text-muted-foreground mb-1">
                {t.research?.queryTitle ?? "Research Query"}
              </p>
              <p className="text-sm">{query}</p>
            </div>

            {/* Report content */}
            {isCompleted && activeJob?.result && (
              <div className="space-y-4">
                <div className="prose prose-sm dark:prose-invert max-w-none border rounded-lg p-4">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {activeJob.result.report}
                  </ReactMarkdown>
                </div>

                {/* Source Documents */}
                {activeJob.result.retrieved_documents &&
                  activeJob.result.retrieved_documents.length > 0 && (
                    <div className="border-t pt-4">
                      <h4 className="font-medium mb-2">
                        Source Documents (
                        {activeJob.result.retrieved_documents.length})
                      </h4>
                      <div className="space-y-2 max-h-[200px] overflow-y-auto">
                        {activeJob.result.retrieved_documents.map((doc, i) => (
                          <a
                            key={i}
                            href={doc.source || "#"}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block rounded-md border p-3 text-sm space-y-1 hover:bg-accent/50 transition-colors cursor-pointer"
                          >
                            <div className="font-medium flex items-center gap-1">
                              <ExternalLink className="h-3 w-3 flex-shrink-0" />
                              {doc.title || doc.source || `Document ${i + 1}`}
                            </div>
                            {doc.snippet && (
                              <p className="text-xs text-muted-foreground line-clamp-2">
                                {doc.snippet}
                              </p>
                            )}
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
              </div>
            )}

            {/* Actions */}
            <div className="flex justify-end gap-2">
              {(isCompleted || isFailed) && (
                <Button
                  variant="outline"
                  onClick={() => handleOpenChange(false)}
                >
                  {t.common?.close ?? "Close"}
                </Button>
              )}
              {isFailed && (
                <Button
                  onClick={() => {
                    setActiveJobId(null);
                    setSavedAsNote(false);
                  }}
                >
                  {t.common?.retry ?? "Retry"}
                </Button>
              )}
            </div>
          </div>
        ) : (
          /* Research form */
          <form onSubmit={handleSubmit} className="space-y-4 py-2">
            {/* Query */}
            <div className="space-y-2">
              <Label>{t.research?.queryTitle ?? "Research Query"}</Label>
              <Textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={
                  t.research?.queryPlaceholder ??
                  "e.g., What are the latest developments in maritime autonomous systems?"
                }
                className="min-h-[80px] text-sm"
                disabled={isSubmitting}
              />
            </div>

            {/* Report Type & Tone — side by side */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t.research?.reportType ?? "Report Type"}</Label>
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
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {reportTypes && (
                  <p className="text-xs text-muted-foreground">
                    {reportTypes.find((rt) => rt.value === reportType)?.description}
                    {" - "}
                    {reportTypes.find((rt) => rt.value === reportType)?.speed ?? ""}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label>{t.research?.toneLabel ?? "Writing Tone"}</Label>
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
                        {tn.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Model Selection */}
            <div className="space-y-2">
              <Label className="flex items-center gap-1">
                <Sparkles className="h-3.5 w-3.5" />
                {t.research?.modelLabel ?? "AI Model"}
              </Label>
              <ModelSelector
                modelType="language"
                value={modelId}
                onChange={setModelId}
                placeholder="Select a model..."
                disabled={isSubmitting}
              />
              <p className="text-xs text-muted-foreground">
                Select the language model to use for generating the report.
              </p>
            </div>

            {/* Submit */}
            <div className="flex justify-end pt-2">
              <Button
                type="submit"
                disabled={!query.trim() || isSubmitting || isLoading}
                className="min-w-[180px]"
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
        )}
      </DialogContent>
    </Dialog>
  );
}
