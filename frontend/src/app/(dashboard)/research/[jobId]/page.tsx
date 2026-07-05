"use client";

import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useResearchJob } from "@/lib/hooks/use-research";
import { ResearchReportView } from "@/components/research/ResearchReportView";
import { ReportTypeLabel, reportDisplayTitle } from "@/components/research/research-shared";
import { formatDateTime } from "@/lib/utils/format-datetime";
import { useTranslation } from "@/lib/hooks/use-translation";

export default function ResearchReportPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const params = useParams();
  const jobId = params?.jobId ? decodeURIComponent(params.jobId as string) : null;
  const { data: job, isLoading } = useResearchJob(jobId);

  const handleBack = () => {
    router.push("/research?tab=jobs");
  };

  return (
    <div className="app-page space-y-6">
      <div className="sticky top-0 z-10 -mx-4 -mt-4 bg-background/95 px-4 pt-4 pb-2 backdrop-blur supports-[backdrop-filter]:bg-background/60 sm:-mx-6 sm:-mt-6 sm:px-6 sm:pt-6 xl:-mx-8 xl:px-8">
        <Button variant="ghost" size="sm" onClick={handleBack} className="-ml-2">
          <ArrowLeft className="mr-2 h-4 w-4" />
          {t.research?.backToHistory ?? "Go back"}
        </Button>
      </div>

      {isLoading || !job ? (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : !job.result ? (
        <div className="flex items-center justify-center py-24 text-center text-muted-foreground">
          {t.research?.reportUnavailable ?? "Report not available"}
        </div>
      ) : (
        <>
          <div className="space-y-1">
            <h1 className="text-2xl font-bold tracking-tight">
              {reportDisplayTitle(job)}
            </h1>
            <div className="flex items-center gap-3 flex-wrap">
              <ReportTypeLabel type={job.report_type} />
              {job.created_at && (
                <span className="text-xs text-muted-foreground">
                  {formatDateTime(job.created_at)}
                </span>
              )}
            </div>
          </div>

          <ResearchReportView job={{ ...job, result: job.result }} />
        </>
      )}
    </div>
  );
}
