"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/hooks/use-auth";
import { useNotebook } from "@/lib/hooks/use-notebooks";
import { useNotes } from "@/lib/hooks/use-notes";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FileText, StickyNote, Columns2 } from "lucide-react";
import { useTranslation } from "@/lib/hooks/use-translation";
import { DocumentGraph } from "@/components/notebooks/DocumentGraph";
import { NotesGraph } from "@/components/notebooks/NotesGraph";

type VizTab = "sources" | "notes" | "split";

/** Read the notebook's selected knowledge-base doc ids from localStorage. */
function readSelectedDocIds(notebookId: string): string[] {
  if (!notebookId || typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(
      `notebook:${notebookId}:selectedNavyDocIds`,
    );
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string").slice(0, 15)
      : [];
  } catch {
    return [];
  }
}

/** Sources panel content: the documents graph or a "needs docs" hint. */
function SourcesPanel({
  docIds,
  canSources,
}: {
  docIds: string[];
  canSources: boolean;
}) {
  const { t } = useTranslation();
  if (canSources) return <DocumentGraph docIds={docIds} className="flex-1" />;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center text-sm text-muted-foreground">
      <FileText className="h-6 w-6" />
      {t.navyDocs?.graphNeedsDocs ??
        "Select at least 2 knowledge base documents to see their relationships."}
    </div>
  );
}

/**
 * Notes panel content: the notes graph. The heuristic disclaimer now lives as
 * an info icon inside the graph's control bar, so this panel mirrors the
 * Sources panel exactly (same flex-fill structure → equal canvas heights).
 */
function NotesPanel({ notebookId }: { notebookId: string }) {
  return <NotesGraph notebookId={notebookId} className="flex-1" />;
}

/**
 * Standalone, full-window data-analytics workspace. Lives outside the dashboard
 * layout (no sidebar) so it runs edge-to-edge in its own browser window/tab,
 * opened from a notebook. Hosts the Sources graph, the Notes graph, or both
 * side-by-side (split).
 */
export default function AnalyticsPage() {
  const { t } = useTranslation();
  const params = useParams();
  const router = useRouter();
  const notebookId = params?.id ? decodeURIComponent(params.id as string) : "";

  // This window doesn't go through the dashboard auth gate — guard it here.
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace("/login");
  }, [authLoading, isAuthenticated, router]);

  const { data: notebook, isLoading: notebookLoading } =
    useNotebook(notebookId);
  const { data: notes } = useNotes(notebookId);

  // Selected docs come from localStorage (this is a separate window). Keep them
  // in sync if the user toggles selections back in the main notebook tab.
  const [docIds, setDocIds] = useState<string[]>([]);
  useEffect(() => {
    if (!notebookId) return;
    setDocIds(readSelectedDocIds(notebookId));
    const onStorage = (e: StorageEvent) => {
      if (e.key === `notebook:${notebookId}:selectedNavyDocIds`) {
        setDocIds(readSelectedDocIds(notebookId));
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [notebookId]);

  const canSources = docIds.length >= 2;
  const hasNotes = (notes?.length ?? 0) >= 1;

  const [tab, setTab] = useState<VizTab>("sources");
  // Auto-pick a sensible default tab once we know what data exists, but only
  // once — don't fight the user's later choice.
  const picked = useRef(false);
  useEffect(() => {
    if (picked.current || notes === undefined) return;
    picked.current = true;
    setTab(canSources ? "sources" : hasNotes ? "notes" : "sources");
  }, [notes, canSources, hasNotes]);

  if (!authLoading && !isAuthenticated) return null; // redirecting

  if (authLoading || notebookLoading) {
    return (
      <div className="h-dvh flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-dvh w-full min-h-0">
      {/* Slim top bar — title + view switcher, no sidebar, no back nav. */}
      <header className="flex-shrink-0 flex items-center gap-3 border-b px-4 py-2.5 min-w-0">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold leading-tight xl:text-lg">
            {t.navyDocs?.visualizeTitle ?? "Data analytics"}
          </h1>
          {notebook?.name && (
            <p className="truncate text-xs text-muted-foreground">
              {notebook.name}
            </p>
          )}
        </div>
        <div className="flex-1" />
        <Tabs value={tab} onValueChange={(v) => setTab(v as VizTab)}>
          <TabsList>
            <TabsTrigger value="sources" className="gap-2">
              <FileText className="h-4 w-4" />
              {t.navyDocs?.vizTabSources ?? "Sources"}
            </TabsTrigger>
            <TabsTrigger value="notes" className="gap-2">
              <StickyNote className="h-4 w-4" />
              {t.navyDocs?.vizTabNotes ?? "Notes"}
            </TabsTrigger>
            <TabsTrigger value="split" className="gap-2">
              <Columns2 className="h-4 w-4" />
              {t.navyDocs?.vizTabSplit ?? "Split"}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </header>

      <main className="flex-1 min-h-0 p-3 overflow-hidden flex flex-col">
        {tab === "sources" && (
          <SourcesPanel docIds={docIds} canSources={canSources} />
        )}
        {tab === "notes" && <NotesPanel notebookId={notebookId} />}
        {tab === "split" && (
          <div className="flex flex-1 min-h-0 flex-col gap-3 lg:flex-row">
            <section className="flex flex-1 min-h-0 min-w-0 flex-col">
              <h2 className="flex-shrink-0 flex items-center gap-1.5 pb-1.5 text-xs font-semibold text-muted-foreground">
                <FileText className="h-3.5 w-3.5" />
                {t.navyDocs?.vizTabSources ?? "Sources"}
              </h2>
              <SourcesPanel docIds={docIds} canSources={canSources} />
            </section>
            <section className="flex flex-1 min-h-0 min-w-0 flex-col lg:border-l lg:pl-3">
              <h2 className="flex-shrink-0 flex items-center gap-1.5 pb-1.5 text-xs font-semibold text-muted-foreground">
                <StickyNote className="h-3.5 w-3.5" />
                {t.navyDocs?.vizTabNotes ?? "Notes"}
              </h2>
              <NotesPanel notebookId={notebookId} />
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
