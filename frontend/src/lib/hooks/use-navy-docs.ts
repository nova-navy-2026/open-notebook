import { useQuery } from "@tanstack/react-query";
import { navyDocsApi } from "@/lib/api/navy-docs";

export const NAVY_DOCS_QUERY_KEY = ["navy-docs"] as const;

export function useNavyDocuments() {
  return useQuery({
    queryKey: NAVY_DOCS_QUERY_KEY,
    queryFn: () => navyDocsApi.list(),
    // The navy corpus rarely changes, so keep results fresh for a long
    // time and don't garbage-collect them when navigating between the
    // /sources page and notebook pages. This makes the sidebar feel
    // instant after the first load.
    staleTime: 30 * 60 * 1000, // 30 minutes — treat as fresh, no refetch
    gcTime: 60 * 60 * 1000, // 1 hour — keep in cache across route changes
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
    // Silent background poll so newly indexed corpus documents show up
    // without forcing the user to reload the page. The backend itself
    // also refreshes its in-process cache from OpenSearch on the same
    // cadence (see api/main.py NAVY_DOCS_REFRESH_SECONDS), so this hits
    // a warm cache and is effectively free.
    refetchInterval: 5 * 60 * 1000, // 5 minutes
    refetchIntervalInBackground: false, // don't poll when tab is hidden
  });
}
