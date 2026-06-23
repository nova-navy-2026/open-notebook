import { useQuery } from "@tanstack/react-query";
import { navyDocsApi } from "@/lib/api/navy-docs";
import { useAuthStore } from "@/lib/stores/auth-store";

export const NAVY_DOCS_QUERY_KEY = ["navy-docs"] as const;
export const NAVY_DOC_GRAPH_QUERY_KEY = ["navy-doc-graph"] as const;
export const NAVY_TOPICS_QUERY_KEY = ["navy-topics"] as const;

/**
 * Fetch the fixed, global topic taxonomy. Used to assign notes to topics
 * client-side (keyword heuristic) for the Notes ↔ Topics visualization.
 */
export function useTopics() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const token = useAuthStore((s) => s.token);

  return useQuery({
    queryKey: NAVY_TOPICS_QUERY_KEY,
    queryFn: () => navyDocsApi.topics(),
    enabled: isAuthenticated && !!token,
    staleTime: 30 * 60 * 1000, // taxonomy is effectively static
    gcTime: 60 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

/**
 * Build the document-relationship graph for a set of navy doc_ids (the
 * notebook's selected documents). Disabled when nothing is selected.
 */
export function useDocumentGraph(docIds: string[], enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const token = useAuthStore((s) => s.token);
  // Stable key regardless of selection order.
  const sortedIds = [...docIds].sort();

  return useQuery({
    queryKey: [...NAVY_DOC_GRAPH_QUERY_KEY, sortedIds],
    queryFn: () => navyDocsApi.graph(docIds),
    enabled: enabled && isAuthenticated && !!token && docIds.length > 0,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

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
