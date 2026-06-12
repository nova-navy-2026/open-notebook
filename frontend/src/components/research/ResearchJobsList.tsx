"use client";
import { formatDateTime } from '@/lib/utils/format-datetime'

import { isValidElement, useRef, useState } from "react";
import type { HTMLAttributes, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components, ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Card,
  CardContent,
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
    react_deep: "ReAct Deep Research",
    plan_and_execute_dr: "Plan-and-Execute Deep Research",
  };
  return (
    <span className="text-xs text-muted-foreground">
      {labels[type] ?? type}
    </span>
  );
}

type TocItem = { level: number; text: string; id: string; index: number; line: number };
type MarkdownHeadingProps = HTMLAttributes<HTMLHeadingElement> & ExtraProps;

function markdownNodeText(node: ReactNode): string {
  if (node == null) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(markdownNodeText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return markdownNodeText(node.props.children);
  }
  return "";
}

function slugifyHeading(text: string) {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function nextHeadingId(counts: Map<string, number>, text: string) {
  const base = slugifyHeading(text) || "section";
  const count = counts.get(base) ?? 0;
  counts.set(base, count + 1);
  return count === 0 ? base : `${base}-${count + 1}`;
}

function isLikelyBareHeading(line: string) {
  const stripped = line.trim().replace(/^\*+|\*+$/g, "");
  if (!stripped) return false;
  if (stripped.length > 100 || /[.!?]\s*$/.test(stripped)) return false;
  if (/^(?:[-*+>]|\d+[.)]\s+|\|)/.test(stripped)) return false;
  if (/https?:\/\/|`|\[[^\]]+\]\([^)]+\)/.test(stripped)) return false;
  if (stripped.includes(":") && !stripped.endsWith(":")) return false;
  const words = stripped.replace(/:$/, "").split(/\s+/);
  if (words.length < 1 || words.length > 12) return false;
  return /^[A-ZÁÉÍÓÚÀÂÊÔÇÃÕ0-9]/.test(stripped);
}

function normalizeReportMarkdown(markdown: string, fallbackTitle: string) {
  const source = (markdown || "").trim();
  if (!source) return source;

  const lines = source.split("\n");
  const output: string[] = [];
  let inFence = false;
  let firstContentSeen = false;
  let hasH1 = /^#\s+\S/m.test(source);

  lines.forEach((line, index) => {
    const stripped = line.trim();
    if (/^```/.test(stripped)) {
      inFence = !inFence;
      output.push(line);
      return;
    }
    if (inFence || !stripped) {
      output.push(line);
      return;
    }
    if (stripped.startsWith("#")) {
      output.push(line);
      firstContentSeen = true;
      return;
    }

    const prevBlank = index === 0 || !lines[index - 1].trim();
    const nextBlank = index + 1 >= lines.length || !lines[index + 1].trim();
    if (!firstContentSeen && !hasH1 && stripped.length <= 140 && !/[.!?]\s*$/.test(stripped)) {
      output.push(`# ${stripped.replace(/:$/, "")}`);
      firstContentSeen = true;
      hasH1 = true;
      return;
    }
    if (firstContentSeen && (prevBlank || nextBlank) && isLikelyBareHeading(stripped)) {
      output.push(`## ${stripped.replace(/:$/, "")}`);
      return;
    }

    output.push(line);
    firstContentSeen = true;
  });

  let normalized = output.join("\n").trim();
  if (!hasH1) {
    const title = fallbackTitle.trim().replace(/[ ,.;:-]+$/, "") || "Research Report";
    normalized = `# ${title}\n\n${normalized}`;
  }
  if (!/^#{2,3}\s+\S/m.test(normalized)) {
    normalized = normalized.replace(/^(#\s+.+)\n+/, "$1\n\n## Síntese\n\n");
  }
  return normalized;
}

// Extract a table of contents from report headings. Keep IDs in lock-step
// with the rendered markdown headings, including duplicate-title suffixes.
function buildToc(markdown: string): TocItem[] {
  const lines = markdown.split("\n");
  const items: TocItem[] = [];
  const counts = new Map<string, number>();
  let inFence = false;
  lines.forEach((raw, lineIndex) => {
    const line = raw.trimEnd();
    if (/^```/.test(line)) {
      inFence = !inFence;
      return;
    }
    if (inFence) return;
    const m = /^(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!m) return;
    const level = m[1].length;
    const text = m[2].replace(/[*_`~]/g, "").trim();
    const id = nextHeadingId(counts, text);
    items.push({ level, text, id, index: items.length, line: lineIndex + 1 });
  });
  return items;
}

function scrollReportHeading(container: HTMLElement | null, headingIndex: number) {
  if (!container) return;

  const heading = container.querySelector<HTMLElement>(
    `[data-report-heading-index="${headingIndex}"]`,
  );
  if (!heading) return;

  const containerRect = container.getBoundingClientRect();
  const headingRect = heading.getBoundingClientRect();
  const containerStyle = window.getComputedStyle(container);
  const paddingTop = Number.parseFloat(containerStyle.paddingTop) || 0;
  const top =
    container.scrollTop +
    headingRect.top -
    containerRect.top -
    paddingTop -
    12;

  container.scrollTo({
    top: Math.max(0, top),
    behavior: "smooth",
  });
}

function createHeadingComponents(toc: TocItem[]): Components {
  const tocByLine = new Map(toc.map((item) => [item.line, item]));
  const counts = new Map<string, number>();
  const Heading = (Tag: "h1" | "h2" | "h3") => {
    const MarkdownHeading = ({ children, node, ...rest }: MarkdownHeadingProps) => {
      const fallbackId = nextHeadingId(counts, markdownNodeText(children));
      const position = (node as { position?: { start?: { line?: number } } } | undefined)?.position;
      const line = position?.start?.line;
      const tocItem = typeof line === "number" ? tocByLine.get(line) : undefined;
      const id = tocItem?.id ?? fallbackId;
      const className = [rest.className, "scroll-mt-4"].filter(Boolean).join(" ");
      return (
        <Tag
          {...rest}
          id={id}
          data-report-heading-id={id}
          data-report-heading-index={tocItem?.index ?? -1}
          className={className}
        >
          {children}
        </Tag>
      );
    };
    MarkdownHeading.displayName = `Markdown${Tag.toUpperCase()}`;
    return MarkdownHeading;
  };

  return {
    h1: Heading("h1"),
    h2: Heading("h2"),
    h3: Heading("h3"),
  };
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
  const reportScrollRef = useRef<HTMLDivElement | null>(null);

  // Fetch the full job with result when selected
  const { data: selectedJob } = useResearchJob(selectedJobId);

  // Resolve a model id to its human-friendly name when possible.
  const resolveModelName = (modelId?: string | null) => {
    if (!modelId) return undefined;
    const found = allModels?.find((m) => m.id === modelId || m.name === modelId);
    return found?.name ?? modelId;
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
                        ? formatDateTime(job.created_at)
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
                const reportMarkdown = normalizeReportMarkdown(
                  selectedJob.result.report,
                  selectedJob.query,
                );
                const toc = buildToc(reportMarkdown);
                const headingComponents = createHeadingComponents(toc);
                return (
                  <>
                  <aside className="min-h-0 border-r bg-muted/30 overflow-y-auto px-3 py-4">
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
                            <button
                              type="button"
                              onClick={() => scrollReportHeading(reportScrollRef.current, item.index)}
                              className="block w-full text-left text-muted-foreground hover:text-foreground hover:underline line-clamp-2"
                            >
                              {item.text}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </aside>

              <div ref={reportScrollRef} className="min-h-0 overflow-y-auto overscroll-contain px-6 pb-6 space-y-4">
              {/* Report Content */}
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={headingComponents}
                >
                  {reportMarkdown}
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
                  onClick={() =>
                    handleCopyReport(
                      normalizeReportMarkdown(selectedJob.result!.report, selectedJob.query),
                    )
                  }
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
                  </>
                );
              })()}
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
