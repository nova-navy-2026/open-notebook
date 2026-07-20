import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'

/**
 * Runtime capability flags from the backend.
 *
 * This deployment usually runs on a closed LAN, so features needing the public
 * internet (adding a source from a URL, web/academic research) are gated on an
 * actual connectivity probe rather than hard-coded off. The UI disables them
 * when `internet` is false instead of letting users hit failures.
 */
export interface Capabilities {
  internet: boolean
  url_sources: boolean
  web_research: boolean
  /** True when pinned offline via FORCE_OFFLINE, not merely a failed probe. */
  forced_offline: boolean
}

export const CAPABILITIES_QUERY_KEY = ['capabilities'] as const

export function useCapabilities() {
  return useQuery<Capabilities>({
    queryKey: CAPABILITIES_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<Capabilities>('/capabilities')
      return response.data
    },
    // The backend caches the probe (INTERNET_CHECK_TTL); mirror that here so
    // the UI isn't refetching constantly, but still notices if a network cable
    // gets plugged in mid-session.
    staleTime: 60_000,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
    // Fail closed: if we can't read capabilities, assume no internet so
    // internet-only options stay disabled.
    retry: 1,
  })
}

/**
 * Convenience: true when internet-dependent features should be usable.
 * Defaults to false while loading or on error (fail closed).
 */
export function useHasInternet(): boolean {
  const { data } = useCapabilities()
  return data?.internet ?? false
}
