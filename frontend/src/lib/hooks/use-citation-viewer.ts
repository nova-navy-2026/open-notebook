import { useMutation, useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { useCitationViewerStore } from '@/lib/stores/citation-viewer-store'
import { citationsApi } from '@/lib/api/citations'

// Re-export the store hook for convenience
export { useCitationViewerStore }

/**
 * Materialize (and cache) a cited navy document. Uses a query rather than a
 * mutation so reopening the same citation is instant — the same snappy feel
 * as the sources tab, which serves stored full_text. The SurrealDB record is
 * still deleted when the panel closes; the panel renders from this response,
 * so a cache-hit reopen doesn't need the record to exist.
 */
export function useCitedDocument(
  ref: string,
  chunkId?: string,
  snippet?: string,
  enabled = true
) {
  return useQuery({
    queryKey: ['citation', ref, chunkId ?? null, snippet ?? null],
    queryFn: () =>
      citationsApi.materialize({
        ref,
        chunk_id: chunkId ?? null,
        snippet: snippet ?? null,
      }),
    enabled,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: (failureCount, error) => {
      // 400/404 are definitive (bad ref, missing doc, ACL) — don't retry.
      const status = isAxiosError(error) ? error.response?.status : undefined
      if (status === 400 || status === 404) return false
      return failureCount < 2
    },
  })
}

export function useDeleteCitation() {
  return useMutation({
    mutationFn: citationsApi.delete,
    onError: (error: unknown) => {
      // Fire-and-forget: the record may already be gone (cache-hit reopens
      // don't recreate it) — never surface this to the user.
      console.warn('[useDeleteCitation] delete failed (non-critical):', error)
    },
  })
}
