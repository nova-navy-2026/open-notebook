"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  CheckCircle2,
  Clock,
  Loader2,
  AlertCircle,
  FileText,
  BookmarkPlus,
  ExternalLink,
  Copy,
  Trash2,
} from "lucide-react";
import {
  useResearchJobs,
  useResearchJob,
  useSaveResearchAsNote,
  useDeleteResearchJob,
} from "@/lib/hooks/use-research";
import { useModels } from "@/lib/hooks/use-models";
import { useQuery } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/lib/api/query-client";
import { useTranslation } from "@/lib/hooks/use-translation";
import { ResearchJob } from "@/lib/types/research";
import { useToast } from "@/lib/hooks/use-toast";
import apiClient from "@/lib/api/client";

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return (
        <Badge variant="default" className="bg-green-600">
          <CheckCircle2 className="mr-1 h-3 w-3" />
          Completed
        </Badge>
      );
    case "running":
      return (
        <Badge variant="default" className="bg-blue-600">
          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          Running
        </Badge>
      );
    case "pending":
      return (
        <Badge variant="secondary">
          <Clock className="mr-1 h-3 w-3" />
          Pending
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive">
          <AlertCircle className="mr-1 h-3 w-3" />
          Failed
        </Badge>
      );
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function ReportTypeLabel({ type }: { type: string }) {
  const labels: Record<string, string> = {
    research_report: "Research Report",
    resource_report: "Resource Report",
    outline_report: "Outline Report",
    custom_report: "Custom Report",
    detailed_report: "Detailed Report",
    subtopic_report: "Subtopic Report",
    deep: "Deep Research",
    ttd_dr: "TTD-DR Deep Research",
  };
  return (
    <span className="text-xs text-muted-foreground">
      {labels[type] ?? type}
    </span>
  );
}

export function ResearchJobsList() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { jobs, isLoading, hasActiveJobs } = useResearchJobs();
  const saveAsNote = useSaveResearchAsNote();
  const deleteJob = useDeleteResearchJob();
  const { data: allModels } = useModels();

  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveJobId, setSaveJobId] = useState<string | null>(null);
  const [selectedNotebookId, setSelectedNotebookId] = useState<string>("");

  // Fetch the full job with result when selected
  const { data: selectedJob } = useResearchJob(selectedJobId);

  // Resolve a model id to its human-friendly name when possible.
  const resolveModelName = (modelId?: string | null) => {
    if (!modelId) return undefined;
    const found = allModels?.find((m) => m.id === modelId || m.name === modelId);
    return found?.name ?? modelId;
  };

  // Extract a simple table of contents from the markdown report (h1-h3).
  const buildToc = (markdown: string) => {
    const lines = markdown.split("\n");
    const items: { level: number; text: string; id: string }[] = [];
    let inFence = false;
    for (const raw of lines) {
      const line = raw.trimEnd();
      if (/^```/.test(line)) {
        inFence = !inFence;
        continue;
      }
      if (inFence) continue;
      const m = /^(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line);
      if (!m) continue;
      const level = m[1].length;
      const text = m[2].replace(/[*_`~]/g, "").trim();
      const id = text
        .toLowerCase()
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-z0-9\s-]/g, "")
        .trim()
        .replace(/\s+/g, "-");
      if (id) items.push({ level, text, id });
    }
    return items;
  };

  // Fetch notebooks for the save dialog
  const { data: notebooks } = useQuery({
    queryKey: QUERY_KEYS.notebooks,
    queryFn: async () => {
      const res = await apiClient.get("/notebooks");
      return res.data;
    },
    enabled: saveDialogOpen,
  });

  const handleCopyReport = (report: string) => {
    navigator.clipboard.writeText(report);
    toast({
      title: t.research?.copied ?? "Copied",
      description: t.research?.copiedDesc ?? "Report copied to clipboard",
    });
  };

  const handleSaveAsNote = async () => {
    if (!saveJobId || !selectedNotebookId) return;
    await saveAsNote.mutateAsync({
      research_id: saveJobId,
      notebook_id: selectedNotebookId,
    });
    setSaveDialogOpen(false);
    setSaveJobId(null);
    setSelectedNotebookId("");
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <FileText className="h-12 w-12 text-muted-foreground mb-4" />
          <p className="text-lg font-medium">
            {t.research?.noJobs ?? "No research jobs yet"}
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            {t.research?.noJobsDesc ??
              "Generate your first research report to see it here."}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <div className="space-y-4">
        {hasActiveJobs && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t.research?.activeJobs ??
              "Research in progress — auto-refreshing..."}
          </div>
        )}

        {jobs.map((job) => (
          <Card key={job.id} className="hover:bg-accent/50 transition-colors">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between">
                <div className="space-y-1 flex-1 mr-4">
                  <CardTitle className="text-base line-clamp-2">
                    {job.query}
                  </CardTitle>
                  <div className="flex items-center gap-2 flex-wrap">
                    <ReportTypeLabel type={job.report_type} />
                    {job.tone && (
                      <Badge variant="outline" className="text-xs py-0">
                        {job.tone}
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {job.created_at
                        ? new Date(job.created_at).toLocaleString()
                        : ""}
                    </span>
                  </div>
                </div>
                <StatusBadge status={job.status} />
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              {job.progress && job.status !== "completed" && (
                <p className="text-sm text-muted-foreground mb-3">
                  {job.progress}
                </p>
              )}
              {job.status === "running" && (
                <div className="mb-3 space-y-1">
                  <Progress value={job.progress_pct ?? 0} className="h-2" />
                  <p className="text-xs text-muted-foreground text-right">
                    {job.progress_pct ?? 0}%
                  </p>
                </div>
              )}
              {job.error && (
                <p className="text-sm text-destructive mb-3">{job.error}</p>
              )}
              {(job.status === "completed" || job.has_result) && (
                <div className="flex gap-2 flex-wrap">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedJobId(job.id)}
                  >
                    <FileText className="mr-1 h-3 w-3" />
                    {t.research?.viewReport ?? "View Report"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setSaveJobId(job.id);
                      setSaveDialogOpen(true);
                    }}
                  >
                    <BookmarkPlus className="mr-1 h-3 w-3" />
                    {t.research?.saveToNotebook ?? "Save to Notebook"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => deleteJob.mutate(job.id)}
                    disabled={deleteJob.isPending}
                  >
                    <Trash2 className="mr-1 h-3 w-3" />
                    {t.research?.delete ?? "Delete"}
                  </Button>
                </div>
              )}
              {job.status !== "completed" && !job.has_result && (
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => deleteJob.mutate(job.id)}
                    disabled={deleteJob.isPending || job.status === "running"}
                  >
                    <Trash2 className="mr-1 h-3 w-3" />
                    {t.research?.delete ?? "Delete"}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Report Viewer Dialog */}
      <Dialog
        open={!!selectedJobId}
        onOpenChange={(open) => !open && setSelectedJobId(null)}
      >
        <DialogContent className="!max-w-4xl sm:!max-w-4xl w-[min(896px,calc(100vw-2rem))] max-h-[90vh] overflow-hidden p-0 flex flex-col">
          <DialogHeader className="px-6 pt-6">
            <DialogTitle>{selectedJob?.query ?? "Research Report"}</DialogTitle>
            <DialogDescription>
              <ReportTypeLabel type={selectedJob?.report_type ?? ""} />
            </DialogDescription>
          </DialogHeader>

          {selectedJob?.result ? (
            <div className="flex-1 min-h-0 overflow-hidden grid grid-cols-[200px_1fr] gap-0">
              {/* Table of contents */}
              {(() => {
                const toc = buildToc(selectedJob.result.report);
                return (
                  <aside className="border-r bg-muted/30 overflow-y-auto px-3 py-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      {t.research?.tableOfContents ?? "Table of Contents"}
                    </p>
                    {toc.length === 0 ? (
                      <p className="text-xs text-muted-foreground">—</p>
                    ) : (
                      <ul className="space-y-1 text-xs">
                        {toc.map((item, i) => (
                          <li
                            key={`${item.id}-${i}`}
                            style={{ paddingLeft: `${(item.level - 1) * 8}px` }}
                          >
                            <a
                              href={`#${item.id}`}
                              onClick={(e) => {
                                e.preventDefault();
                                const el = document.getElementById(item.id);
                                if (el)
                                  el.scrollIntoView({
                                    behavior: "smooth",
                                    block: "start",
                                  });
                              }}
                              className="text-muted-foreground hover:text-foreground hover:underline line-clamp-2"
                            >
                              {item.text}
                            </a>
                          </li>
                        ))}
                      </ul>
                    )}
                  </aside>
                );
              })()}

              <div className="overflow-y-auto px-6 pb-6 space-y-4">
              {/* Report Content */}
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    h1: ({ children, ...rest }) => {
                      const text = String(
                        Array.isArray(children) ? children.join("") : children,
                      );
                      const id = text
                        .toLowerCase()
                        .normalize("NFKD")
                        .replace(/[\u0300-\u036f]/g, "")
                        .replace(/[^a-z0-9\s-]/g, "")
                        .trim()
                        .replace(/\s+/g, "-");
                      return (
                        <h1 id={id} {...rest}>
                          {children}
                        </h1>
                      );
                    },
                    h2: ({ children, ...rest }) => {
                      const text = String(
                        Array.isArray(children) ? children.join("") : children,
                      );
                      const id = text
                        .toLowerCase()
                        .normalize("NFKD")
                        .replace(/[\u0300-\u036f]/g, "")
                        .replace(/[^a-z0-9\s-]/g, "")
                        .trim()
                        .replace(/\s+/g, "-");
                      return (
                        <h2 id={id} {...rest}>
                          {children}
                        </h2>
                      );
                    },
                    h3: ({ children, ...rest }) => {
                      const text = String(
                        Array.isArray(children) ? children.join("") : children,
                      );
                      const id = text
                        .toLowerCase()
                        .normalize("NFKD")
                        .replace(/[\u0300-\u036f]/g, "")
                        .replace(/[^a-z0-9\s-]/g, "")
                        .trim()
                        .replace(/\s+/g, "-");
                      return (
                        <h3 id={id} {...rest}>
                          {children}
                        </h3>
                      );
                    },
                  }}
                >
                  {selectedJob.result.report}
                </ReactMarkdown>
              </div>

              {/* Source Documents */}
              {selectedJob.result.retrieved_documents &&
                selectedJob.result.retrieved_documents.length > 0 && (
                  <div className="border-t pt-4">
                    <h4 className="font-medium mb-2">
                      {t.research?.sourceDocuments ?? "Source Documents"} (
                      {selectedJob.result.retrieved_documents.length})
                    </h4>
                    <div className="space-y-2 max-h-[300px] overflow-y-auto">
                      {selectedJob.result.retrieved_documents.map((doc, i) => (
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
                            <p className="text-xs text-muted-foreground line-clamp-3">
                              {doc.snippet}
                            </p>
                          )}
                        </a>
                      ))}
                    </div>
                  </div>
                )}

              {/* Settings used */}
              <div className="border-t pt-4">
                <h4 className="font-medium mb-2">
                  {t.research?.researchConfiguration ?? "Research Configuration"}
                </h4>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">
                    <ReportTypeLabel type={selectedJob.report_type} />
                  </Badge>
                  {selectedJob.result.tone && (
                    <Badge variant="outline">
                      {(t.research?.tonePrefix ?? "Tone")}: {selectedJob.result.tone}
                    </Badge>
                  )}
                  {selectedJob.result.model_id && (
                    <Badge variant="outline">
                      {(t.research?.modelPrefix ?? "Model")}: {resolveModelName(selectedJob.result.model_id)}
                    </Badge>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-2 border-t pt-4">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleCopyReport(selectedJob.result!.report)}
                >
                  <Copy className="mr-1 h-3 w-3" />
                  {t.research?.copyReport ?? "Copy Report"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setSaveJobId(selectedJob.id);
                    setSaveDialogOpen(true);
                  }}
                >
                  <BookmarkPlus className="mr-1 h-3 w-3" />
                  {t.research?.saveToNotebook ?? "Save to Notebook"}
                </Button>
              </div>
            </div>
            </div>
          ) : (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Save to Notebook Dialog */}
      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <DialogContent className="!max-w-md sm:!max-w-md w-[min(480px,calc(100vw-2rem))]">
          <DialogHeader>
            <DialogTitle>
              {t.research?.saveToNotebook ?? "Save to Notebook"}
            </DialogTitle>
            <DialogDescription>
              {t.research?.saveToNotebookDesc ??
                "Choose a notebook to save this research report as a note."}
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
                    t.research?.selectNotebook ?? "Select a notebook..."
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
              <Button
                variant="outline"
                onClick={() => setSaveDialogOpen(false)}
              >
                {t.common?.cancel ?? "Cancel"}
              </Button>
              <Button
                onClick={handleSaveAsNote}
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
    </>
  );
}
