"use client";

import { isValidElement, useState } from "react";
import type { HTMLAttributes, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components, ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  ExternalLink,
  Copy,
  BookmarkPlus,
  Pencil,
  Save,
  X,
  Loader2,
} from "lucide-react";
import { useCitationViewerStore } from "@/lib/stores/citation-viewer-store";
import { useDirectUpdateReport } from "@/lib/hooks/use-research";
import { useModels } from "@/lib/hooks/use-models";
import { useTranslation } from "@/lib/hooks/use-translation";
import { useToast } from "@/lib/hooks/use-toast";
import { ReportTypeLabel, reportDisplayTitle } from "@/components/research/research-shared";
import { SaveToNotebookDialog } from "@/components/research/SaveToNotebookDialog";
import type { ResearchJob, ResearchResultData } from "@/lib/types/research";

type TocItem = { level: number; text: string; id: string; index: number; line: number };
type MarkdownHeadingProps = HTMLAttributes<HTMLHeadingElement> & ExtraProps;

/**
 * Link renderer for research report markdown. Reports reference corpus
 * documents as `opensearch://{index}/{chunk_id}` refs or bare filenames —
 * neither is a real web URL, and letting the browser navigate them opens
 * dead tabs / 404s. Route them to the citation viewer instead; only real
 * web URLs open in a new tab.
 */
function ReportLink({
  href,
  children,
  ...props
}: HTMLAttributes<HTMLAnchorElement> & { href?: string }) {
  const openCitation = useCitationViewerStore((s) => s.openCitation);
  const isWeb = !!href && /^(https?:|mailto:|#)/i.test(href);

  if (href && !isWeb) {
    let decoded = href;
    try {
      decoded = decodeURIComponent(href);
    } catch {
      /* keep raw */
    }
    const ref = /^(navy:|opensearch:\/\/)/.test(decoded) ? decoded : `navy:${decoded}`;
    return (
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          openCitation({ kind: "navy", ref });
        }}
        className="text-primary hover:underline cursor-pointer inline text-left font-medium"
      >
        {children}
      </button>
    );
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      {...props}
      className="text-primary hover:underline"
    >
      {children}
    </a>
  );
}

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

function scrollToHeading(headingIndex: number) {
  const heading = document.querySelector<HTMLElement>(
    `[data-report-heading-index="${headingIndex}"]`,
  );
  heading?.scrollIntoView({ behavior: "smooth", block: "start" });
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

interface ResearchReportViewProps {
  job: ResearchJob & { result: ResearchResultData };
}

export function ResearchReportView({ job }: ResearchReportViewProps) {
  const { t } = useTranslation();
  const openCitation = useCitationViewerStore((s) => s.openCitation);
  const { toast } = useToast();
  const { data: allModels } = useModels();
  const directUpdate = useDirectUpdateReport();

  const [editMode, setEditMode] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  const resolveModelName = (modelId?: string | null) => {
    if (!modelId) return undefined;
    const found = allModels?.find((m) => m.id === modelId || m.name === modelId);
    return found?.name ?? modelId;
  };

  const handleCopyReport = (report: string) => {
    navigator.clipboard.writeText(report);
    toast({
      title: t.research?.copied ?? "Copied",
      description: t.research?.copiedDesc ?? "Report copied to clipboard",
    });
  };

  const reportMarkdown = normalizeReportMarkdown(job.result.report, reportDisplayTitle(job));
  const toc = buildToc(reportMarkdown);
  const headingComponents = createHeadingComponents(toc);

  return (
    <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-6">
      {/* Table of contents */}
      <aside className="md:sticky md:top-4 md:self-start md:max-h-[calc(100vh-6rem)] overflow-y-auto rounded-md border bg-muted/30 px-3 py-4">
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
                  onClick={() => scrollToHeading(item.index)}
                  className="block w-full text-left text-muted-foreground hover:text-foreground hover:underline line-clamp-2"
                >
                  {item.text}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className="min-w-0 space-y-4">
        {/* Report Content */}
        {editMode ? (
          <Textarea
            className="min-h-[60vh] font-mono text-xs resize-none"
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
          />
        ) : (
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{ ...headingComponents, a: ReportLink }}
            >
              {reportMarkdown}
            </ReactMarkdown>
          </div>
        )}

        {/* Source Documents */}
        {job.result.retrieved_documents && job.result.retrieved_documents.length > 0 && (
          <div className="border-t pt-4">
            <h4 className="font-medium mb-2">
              {t.research?.sourceDocuments ?? "Source Documents"} (
              {job.result.retrieved_documents.length})
            </h4>
            <div className="space-y-2">
              {job.result.retrieved_documents.map((doc, i) => {
                // Corpus documents arrive as navy:/opensearch:// refs or bare
                // filenames — navigating those opens dead tabs or 404s. Only
                // real web URLs are external links; everything else opens in
                // the citation viewer. Jobs saved before refs were emitted
                // have an empty source but a title shaped "{doc}.pdf, p.{N}"
                // — derive the ref from it so old reports stay clickable.
                const isWebUrl = !!doc.source && /^https?:\/\//i.test(doc.source);
                let citationRef: string | null = null;
                if (doc.source && !isWebUrl) {
                  citationRef = /^(navy:|opensearch:\/\/)/.test(doc.source)
                    ? doc.source
                    : `navy:${doc.source}`;
                } else if (!doc.source && doc.title) {
                  const m = doc.title.match(/^(.+?),\s*p\.\s*(\d+)\s*$/);
                  if (m) citationRef = `navy:${m[1]}:p${m[2]}`;
                }
                const inner = (
                  <>
                    <div className="font-medium flex items-center gap-1">
                      <ExternalLink className="h-3 w-3 flex-shrink-0" />
                      {doc.title || doc.source || `Document ${i + 1}`}
                    </div>
                    {doc.snippet && (
                      <p className="text-xs text-muted-foreground line-clamp-3">
                        {doc.snippet}
                      </p>
                    )}
                  </>
                );
                if (citationRef) {
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() =>
                        openCitation({
                          kind: "navy",
                          ref: citationRef,
                          snippet: doc.snippet || undefined,
                        })
                      }
                      className="block w-full rounded-md border p-3 text-left text-sm space-y-1 hover:bg-accent/50 transition-colors cursor-pointer"
                    >
                      {inner}
                    </button>
                  );
                }
                if (isWebUrl) {
                  return (
                    <a
                      key={i}
                      href={doc.source}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block rounded-md border p-3 text-sm space-y-1 hover:bg-accent/50 transition-colors cursor-pointer"
                    >
                      {inner}
                    </a>
                  );
                }
                // No usable target — render a plain card, never a dead
                // new-tab link.
                return (
                  <div key={i} className="block rounded-md border p-3 text-sm space-y-1">
                    {inner}
                  </div>
                );
              })}
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
              <ReportTypeLabel type={job.report_type} />
            </Badge>
            {job.result.tone && (
              <Badge variant="outline">
                {(t.research?.tonePrefix ?? "Tone")}: {job.result.tone}
              </Badge>
            )}
            {job.result.model_id && (
              <Badge variant="outline">
                {(t.research?.modelPrefix ?? "Model")}: {resolveModelName(job.result.model_id)}
              </Badge>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2 border-t pt-4 flex-wrap">
          {!editMode && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleCopyReport(reportMarkdown)}
              >
                <Copy className="mr-1 h-3 w-3" />
                {t.research?.copyReport ?? "Copy Report"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSaveDialogOpen(true)}
              >
                <BookmarkPlus className="mr-1 h-3 w-3" />
                {t.research?.saveToNotebook ?? "Save to Workspace"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditContent(job.result.report);
                  setEditMode(true);
                }}
              >
                <Pencil className="mr-1 h-3 w-3" />
                {t.research?.editReport ?? "Edit"}
              </Button>
            </>
          )}
          {editMode && (
            <>
              <Button
                size="sm"
                disabled={directUpdate.isPending}
                onClick={async () => {
                  await directUpdate.mutateAsync({ jobId: job.id, report: editContent });
                  setEditMode(false);
                }}
              >
                {directUpdate.isPending ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : (
                  <Save className="mr-1 h-3 w-3" />
                )}
                {t.common?.save ?? "Save"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditMode(false);
                  setEditContent("");
                }}
              >
                <X className="mr-1 h-3 w-3" />
                {t.common?.cancel ?? "Cancel"}
              </Button>
            </>
          )}
        </div>
      </div>

      <SaveToNotebookDialog
        jobId={job.id}
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
      />
    </div>
  );
}
