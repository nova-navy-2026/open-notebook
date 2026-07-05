"use client";
import { formatDateTime } from '@/lib/utils/format-datetime'

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  FileText,
  BookmarkPlus,
  Loader2,
  Trash2,
} from "lucide-react";
import { useResearchJobs, useDeleteResearchJob } from "@/lib/hooks/use-research";
import { StatusBadge, ReportTypeLabel, reportDisplayTitle } from "@/components/research/research-shared";
import { SaveToNotebookDialog } from "@/components/research/SaveToNotebookDialog";
import { saveScrollPosition, consumeScrollPosition } from "@/lib/utils/scroll-restore";
import { useTranslation } from "@/lib/hooks/use-translation";

const JOBS_SCROLL_KEY = "research-jobs";

export function ResearchJobsList() {
  const { t } = useTranslation();
  const router = useRouter();
  const { jobs, isLoading, hasActiveJobs } = useResearchJobs();
  const deleteJob = useDeleteResearchJob();

  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveJobId, setSaveJobId] = useState<string | null>(null);

  // Restore scroll position after returning from a report page, once the
  // list has actually rendered so there's content to scroll to.
  useEffect(() => {
    if (jobs.length === 0) return;
    const saved = consumeScrollPosition(JOBS_SCROLL_KEY);
    if (saved == null) return;
    requestAnimationFrame(() => {
      const el = document.getElementById("app-scroll-container");
      if (el) el.scrollTop = saved;
    });
  }, [jobs.length]);

  const handleViewReport = (jobId: string) => {
    saveScrollPosition(JOBS_SCROLL_KEY);
    router.push(`/research/${jobId}`);
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
                    {reportDisplayTitle(job)}
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
                    onClick={() => handleViewReport(job.id)}
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
                    {t.research?.saveToNotebook ?? "Save to Workspace"}
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

      <SaveToNotebookDialog
        jobId={saveJobId}
        open={saveDialogOpen}
        onOpenChange={(open) => {
          setSaveDialogOpen(open);
          if (!open) setSaveJobId(null);
        }}
      />
    </>
  );
}
