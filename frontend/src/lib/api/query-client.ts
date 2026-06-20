import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Always read fresh from the database. Data is marked stale immediately,
      // so every page mount / tab focus / reconnect refetches from the server
      // (which is stateless and always queries SurrealDB). The cache (gcTime) is
      // kept only to render instantly while the fresh data loads
      // (stale-while-revalidate) — it is never the source of truth.
      staleTime: 0,
      gcTime: 10 * 60 * 1000, // 10 minutes (only for instant re-render)
      retry: 2,
      refetchOnMount: true,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
    mutations: {
      retry: 1,
    },
  },
})

export const QUERY_KEYS = {
  notebooks: ['notebooks'] as const,
  notebook: (id: string) => ['notebooks', id] as const,
  notes: (notebookId?: string) => ['notes', notebookId] as const,
  note: (id: string) => ['notes', id] as const,
  sources: (notebookId?: string) => ['sources', notebookId] as const,
  sourcesInfinite: (notebookId: string) => ['sources', 'infinite', notebookId] as const,
  source: (id: string) => ['sources', id] as const,
  settings: ['settings'] as const,
  sourceChatSessions: (sourceId: string) => ['source-chat', sourceId, 'sessions'] as const,
  sourceChatSession: (sourceId: string, sessionId: string) => ['source-chat', sourceId, 'sessions', sessionId] as const,
  notebookChatSessions: (notebookId: string) => ['notebook-chat', notebookId, 'sessions'] as const,
  notebookChatSession: (sessionId: string) => ['notebook-chat', 'sessions', sessionId] as const,
  globalChatSessions: ['global-chat', 'sessions'] as const,
  globalChatSession: (sessionId: string) => ['global-chat', 'sessions', sessionId] as const,
  podcastEpisodes: ['podcasts', 'episodes'] as const,
  podcastEpisode: (episodeId: string) => ['podcasts', 'episodes', episodeId] as const,
  episodeProfiles: ['podcasts', 'episode-profiles'] as const,
  speakerProfiles: ['podcasts', 'speaker-profiles'] as const,
  languages: ['languages'] as const,
  researchJobs: ['research', 'jobs'] as const,
  researchJob: (jobId: string) => ['research', 'jobs', jobId] as const,
  researchReportTypes: ['research', 'report-types'] as const,
  researchTones: ['research', 'tones'] as const,
  researchSources: ['research', 'sources'] as const,
}
