import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { researchApi } from "@/lib/api/research";
import { QUERY_KEYS } from "@/lib/api/query-client";
import { useToast } from "@/lib/hooks/use-toast";
import { useTranslation } from "@/lib/hooks/use-translation";
import { getApiErrorKey } from "@/lib/utils/error-handler";
import {
  ResearchGenerateRequest,
  ResearchJob,
  SaveAsNoteRequest,
  isResearchActive,
} from "@/lib/types/research";

function readJobsFromCache(data: unknown): ResearchJob[] {
  if (Array.isArray(data)) return data as ResearchJob[];
  const maybePayload = data as { jobs?: ResearchJob[] } | undefined;
  return maybePayload?.jobs ?? [];
}

/**
 * Hook to fetch available report types (cached forever since they're static)
 */
export function useReportTypes() {
  return useQuery({
    queryKey: QUERY_KEYS.researchReportTypes,
    queryFn: researchApi.getReportTypes,
    staleTime: Infinity,
  });
}

/**
 * Hook to fetch available writing tones
 */
export function useResearchTones() {
  return useQuery({
    queryKey: QUERY_KEYS.researchTones,
    queryFn: researchApi.getTones,
    staleTime: Infinity,
  });
}

/**
 * Hook to fetch available report sources
 */
export function useResearchSources() {
  return useQuery({
    queryKey: QUERY_KEYS.researchSources,
    queryFn: researchApi.getSources,
    staleTime: Infinity,
  });
}

/**
 * Hook to list research jobs with auto-refresh when jobs are active
 */
export function useResearchJobs(options?: { autoRefresh?: boolean }) {
  const { autoRefresh = true } = options ?? {};

  const query = useQuery({
    queryKey: QUERY_KEYS.researchJobs,
    queryFn: researchApi.listJobs,
    select: (data) => data.jobs,
    refetchInterval: (current) => {
      if (!autoRefresh) return false;

      const jobs = readJobsFromCache(current.state.data);
      if (!jobs || jobs.length === 0) return false;

      // Auto-refresh every 3s if any jobs are active
      return jobs.some((j) => isResearchActive(j.status)) ? 3000 : false;
    },
  });

  const jobs = useMemo(() => query.data ?? [], [query.data]);

  return {
    ...query,
    jobs,
    hasActiveJobs: jobs.some((j) => isResearchActive(j.status)),
  };
}

/**
 * Hook to get a specific research job with auto-polling while active
 */
export function useResearchJob(jobId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.researchJob(jobId ?? ""),
    queryFn: () => researchApi.getJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (current) => {
      const data = current.state.data as ResearchJob | undefined;
      if (!data) return 3000;
      return isResearchActive(data.status) ? 3000 : false;
    },
  });
}

/**
 * Hook to submit a research generation request
 */
export function useGenerateResearch() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { t } = useTranslation();

  return useMutation({
    mutationFn: (payload: ResearchGenerateRequest) =>
      researchApi.generateResearch(payload),
    onSuccess: async () => {
      await queryClient.refetchQueries({ queryKey: QUERY_KEYS.researchJobs });
      toast({
        title: t.research?.generationStarted ?? "Research Started",
        description:
          t.research?.generationStartedDesc ??
          "Your research is being generated. Check back shortly.",
      });
    },
    onError: (error: unknown) => {
      toast({
        title: t.research?.failedToStart ?? "Failed to Start Research",
        description: getApiErrorKey(error, t.common.error),
        variant: "destructive",
      });
    },
  });
}

/**
 * Hook to delete a research job
 */
export function useDeleteResearchJob() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { t } = useTranslation();

  return useMutation({
    mutationFn: (jobId: string) => researchApi.deleteJob(jobId),
    onSuccess: (_data, jobId) => {
      queryClient.removeQueries({ queryKey: QUERY_KEYS.researchJob(jobId) });
      queryClient.refetchQueries({ queryKey: QUERY_KEYS.researchJobs });
    },
    onError: (error: unknown) => {
      toast({
        title: t.research?.failedToDelete ?? "Failed to Delete",
        description: getApiErrorKey(error, t.common.error),
        variant: "destructive",
      });
    },
  });
}

/**
 * Hook to save a research result as a notebook note
 */
export function useSaveResearchAsNote() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { t } = useTranslation();

  return useMutation({
    mutationFn: (payload: SaveAsNoteRequest) => researchApi.saveAsNote(payload),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["notes"] });
      toast({
        title: t.research?.savedAsNote ?? "Saved as Note",
        description: data.message,
      });
    },
    onError: (error: unknown) => {
      toast({
        title: t.research?.failedToSave ?? "Failed to Save",
        description: getApiErrorKey(error, t.common.error),
        variant: "destructive",
      });
    },
  });
}
