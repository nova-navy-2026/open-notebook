import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Clock, Loader2, AlertCircle } from "lucide-react";

export function StatusBadge({ status }: { status: string }) {
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

export const REPORT_TYPE_LABELS: Record<string, string> = {
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
  meeting_minutes: "Ata da Reunião",
};

// Display names for the transcript document styles (transcription menu/chat).
const TRANSCRIPT_STYLE_LABELS: Record<string, string> = {
  ata: "Ata da Reunião",
  summary: "Resumo",
  conversation: "Conversa / Diálogo",
  literal: "Transcrição",
};

export function ReportTypeLabel({ type }: { type: string }) {
  return (
    <span className="text-xs text-muted-foreground">
      {REPORT_TYPE_LABELS[type] ?? type}
    </span>
  );
}

/**
 * Title to show for a research job in the list card, the report page header,
 * and the report document itself.
 *
 * Priority:
 *   1. the title the user typed in the transcription menu (`job.title`);
 *   2. for an untitled transcript report, the document-type name derived from
 *      `report_style` ("Ata da Reunião", "Conversa / Diálogo", …);
 *   3. a short, single-line query — a normal research question;
 *   4. the document's own H1 heading, then the report-type label as a last
 *      resort. Never the raw transcript (which `job.query` holds for transcript
 *      reports).
 */
export function reportDisplayTitle(job: {
  query?: string;
  report_type: string;
  title?: string | null;
  report_style?: string | null;
  result?: { report?: string } | null;
}): string {
  const title = (job.title ?? "").trim();
  if (title) return title;

  if (job.report_style) {
    return TRANSCRIPT_STYLE_LABELS[job.report_style] ?? "Documento";
  }
  if (job.report_type === "meeting_minutes") return "Ata da Reunião";

  const query = (job.query ?? "").trim();
  if (query && query.length <= 120 && !query.includes("\n")) return query;

  const h1 = (job.result?.report ?? "").match(/^#\s+(.+?)\s*$/m)?.[1]?.trim();
  if (h1) return h1;

  return REPORT_TYPE_LABELS[job.report_type] ?? "Relatório";
}
