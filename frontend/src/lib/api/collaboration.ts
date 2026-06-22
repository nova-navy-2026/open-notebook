import apiClient from './client'
import {
  CreateInviteRequest,
  NotebookInviteResponse,
  NotebookMemberResponse,
} from '@/lib/types/api'

export const collaborationApi = {
  // --- members ---
  listMembers: async (notebookId: string) => {
    const response = await apiClient.get<NotebookMemberResponse[]>(
      `/notebooks/${notebookId}/members`
    )
    return response.data
  },

  removeMember: async (notebookId: string, userId: string) => {
    const response = await apiClient.delete(
      `/notebooks/${notebookId}/members/${encodeURIComponent(userId)}`
    )
    return response.data
  },

  // --- invites (owner) ---
  listInvites: async (notebookId: string) => {
    const response = await apiClient.get<NotebookInviteResponse[]>(
      `/notebooks/${notebookId}/invites`
    )
    return response.data
  },

  createInvite: async (notebookId: string, data: CreateInviteRequest) => {
    const response = await apiClient.post<NotebookInviteResponse>(
      `/notebooks/${notebookId}/invites`,
      data
    )
    return response.data
  },

  revokeInvite: async (notebookId: string, inviteId: string) => {
    const response = await apiClient.delete(
      `/notebooks/${notebookId}/invites/${encodeURIComponent(inviteId)}`
    )
    return response.data
  },

  // --- invitee-facing ---
  myInvites: async () => {
    const response = await apiClient.get<NotebookInviteResponse[]>('/invites')
    return response.data
  },

  acceptInvite: async (inviteId: string) => {
    const response = await apiClient.post(
      `/invites/${encodeURIComponent(inviteId)}/accept`
    )
    return response.data
  },

  declineInvite: async (inviteId: string) => {
    const response = await apiClient.post(
      `/invites/${encodeURIComponent(inviteId)}/decline`
    )
    return response.data
  },

  acceptLink: async (token: string) => {
    const response = await apiClient.post<{ notebook_id: string }>(
      '/invites/accept-link',
      { token }
    )
    return response.data
  },
}
