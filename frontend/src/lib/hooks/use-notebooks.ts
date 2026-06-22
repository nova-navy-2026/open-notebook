import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notebooksApi } from '@/lib/api/notebooks'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateNotebookRequest, UpdateNotebookRequest } from '@/lib/types/api'

export function useNotebooks(archived?: boolean) {
  return useQuery({
    queryKey: [...QUERY_KEYS.notebooks, { archived }],
    queryFn: () => notebooksApi.list({ archived, order_by: 'updated desc' }),
    staleTime: 30_000,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  })
}

export function useNotebook(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.notebook(id),
    queryFn: () => notebooksApi.get(id),
    enabled: !!id,
    // Collaborative notebooks poll so shared state (e.g. the navy-corpus
    // selection changed by another member) refreshes automatically. Private
    // notebooks don't poll.
    refetchInterval: (query) =>
      query.state.data?.collaborative ? 10_000 : false,
    refetchOnWindowFocus: true,
  })
}

export function useCreateNotebook() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: CreateNotebookRequest) => notebooksApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      toast({
        title: t.common.success,
        description: t.notebooks.createSuccess,
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: t(getApiErrorKey(error, t.common.error)),
        variant: 'destructive',
      })
    },
  })
}

export function useUpdateNotebook() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateNotebookRequest }) =>
      notebooksApi.update(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebook(id) })
      toast({
        title: t.common.success,
        description: t.notebooks.updateSuccess,
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: t(getApiErrorKey(error, t.common.error)),
        variant: 'destructive',
      })
    },
  })
}

export function useNotebookDeletePreview(id: string, enabled: boolean = false) {
  return useQuery({
    queryKey: [...QUERY_KEYS.notebook(id), 'delete-preview'],
    queryFn: () => notebooksApi.deletePreview(id),
    enabled: !!id && enabled,
  })
}

/**
 * Persist the shared navy-corpus document selection for a notebook. Used by
 * collaborative notebooks so the selection lives server-side (shared by all
 * members) rather than in browser localStorage. Updates the notebook cache on
 * success; stays quiet (no success toast) since it fires on each toggle.
 */
export function useUpdateNavyDocs() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ id, docIds }: { id: string; docIds: string[] }) =>
      notebooksApi.updateNavyDocs(id, docIds),
    onSuccess: (updated, { id }) => {
      queryClient.setQueryData(QUERY_KEYS.notebook(id), updated)
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: t(getApiErrorKey(error, t.common.error)),
        variant: 'destructive',
      })
    },
  })
}

export function useDeleteNotebook() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({
      id,
      deleteExclusiveSources = false,
    }: {
      id: string
      deleteExclusiveSources?: boolean
    }) => notebooksApi.delete(id, deleteExclusiveSources),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      // Also invalidate sources since some may have been deleted
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      toast({
        title: t.common.success,
        description: t.notebooks.deleteSuccess,
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: t(getApiErrorKey(error, t.common.error)),
        variant: 'destructive',
      })
    },
  })
}