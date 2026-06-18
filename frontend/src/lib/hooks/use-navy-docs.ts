import { useQuery } from "@tanstack/react-query";
import { navyDocsApi } from "@/lib/api/navy-docs";
import { useAuthStore } from "@/lib/stores/auth-store";

export const NAVY_DOCS_QUERY_KEY = ["navy-docs"] as const;

export function useNavyDocuments() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const token = useAuthStore((s) => s.token);

  return useQuery({
    queryKey: NAVY_DOCS_QUERY_KEY,
    queryFn: () => navyDocsApi.list(),
    // Only fetch when there is a valid session. Without this guard the query
    // can fire before the auth token is flushed to localStorage by the
    // persist middleware, caching an empty result that then stays "fresh"
    // for 30 minutes and never re-fetches on subsequent mounts.
    enabled: isAuthenticated && !!token,
    staleTime: 5 * 60 * 1000, // 5 minutes — matches backend in-process cache TTL
    gcTime: 60 * 60 * 1000, // 1 hour — keep in cache across route changes
    refetchOnWindowFocus: false,
    refetchOnMount: true, // refetch on mount if data is stale (>5 min) so empty results self-correct
    refetchOnReconnect: false,
    // Silent background poll so newly indexed corpus documents show up
    // without forcing the user to reload the page.
    refetchInterval: 5 * 60 * 1000, // 5 minutes
    refetchIntervalInBackground: false, // don't poll when tab is hidden
  });
}
