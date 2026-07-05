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

export function ReportTypeLabel({ type }: { type: string }) {
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
    meeting_minutes: "Ata da Reunião",
  };
  return (
    <span className="text-xs text-muted-foreground">
      {labels[type] ?? type}
    </span>
  );
}
