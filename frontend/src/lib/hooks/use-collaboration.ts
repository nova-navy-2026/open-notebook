import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { collaborationApi } from '@/lib/api/collaboration'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { CreateInviteRequest } from '@/lib/types/api'

export function useNotebookMembers(notebookId: string, enabled = true) {
  return useQuery({
    queryKey: QUERY_KEYS.notebookMembers(notebookId),
    queryFn: () => collaborationApi.listMembers(notebookId),
    enabled: !!notebookId && enabled,
    // Poll while enabled (i.e. the share dialog is open) so the owner sees a
    // member appear as soon as an invited user accepts — without the owner's
    // client there is no other signal that membership changed.
    refetchInterval: enabled ? 8_000 : false,
    refetchOnWindowFocus: true,
  })
}

export function useNotebookInvites(notebookId: string, enabled = true) {
  return useQuery({
    queryKey: QUERY_KEYS.notebookInvites(notebookId),
    queryFn: () => collaborationApi.listInvites(notebookId),
    enabled: !!notebookId && enabled,
    // Poll while the dialog is open so a pending invite that gets accepted
    // (and thus disappears from the pending list) refreshes promptly.
    refetchInterval: enabled ? 8_000 : false,
    refetchOnWindowFocus: true,
  })
}

/** Pending invitations addressed to the current user (notifications inbox). */
export function useMyInvites(pollMs = 30_000) {
  return useQuery({
    queryKey: QUERY_KEYS.myInvites,
    queryFn: () => collaborationApi.myInvites(),
    refetchInterval: pollMs,
    refetchOnWindowFocus: true,
  })
}

export function useCreateInvite(notebookId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: CreateInviteRequest) =>
      collaborationApi.createInvite(notebookId, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookInvites(notebookId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookMembers(notebookId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebook(notebookId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      if (variables.invite_type === 'email') {
        toast({ title: t.common.success, description: t.collaboration.inviteSent })
      }
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error, (key) => t(key), 'common.error'),
        variant: 'destructive',
      })
    },
  })
}

export function useRevokeInvite(notebookId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (inviteId: string) =>
      collaborationApi.revokeInvite(notebookId, inviteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookInvites(notebookId) })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error, (key) => t(key), 'common.error'),
        variant: 'destructive',
      })
    },
  })
}

export function useRemoveMember(notebookId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (userId: string) =>
      collaborationApi.removeMember(notebookId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookMembers(notebookId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebook(notebookId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      toast({ title: t.common.success, description: t.collaboration.memberRemoved })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error, (key) => t(key), 'common.error'),
        variant: 'destructive',
      })
    },
  })
}

export function useRespondToInvite() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.myInvites })
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
  }

  const accept = useMutation({
    mutationFn: (inviteId: string) => collaborationApi.acceptInvite(inviteId),
    onSuccess: () => {
      invalidate()
      toast({ title: t.common.success, description: t.collaboration.joinedNotebook })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error, (key) => t(key), 'common.error'),
        variant: 'destructive',
      })
    },
  })

  const decline = useMutation({
    mutationFn: (inviteId: string) => collaborationApi.declineInvite(inviteId),
    onSuccess: invalidate,
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error, (key) => t(key), 'common.error'),
        variant: 'destructive',
      })
    },
  })

  return { accept, decline }
}
