"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { NotebookHeader } from "../components/NotebookHeader";
import { SourcesColumn } from "../components/SourcesColumn";
import { NotesColumn } from "../components/NotesColumn";
import { ChatColumn } from "../components/ChatColumn";
import { useNotebook } from "@/lib/hooks/use-notebooks";
import { useNotebookSources } from "@/lib/hooks/use-sources";
import { useNotes } from "@/lib/hooks/use-notes";
import { useNavyDocuments } from "@/lib/hooks/use-navy-docs";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { useNotebookColumnsStore } from "@/lib/stores/notebook-columns-store";
import { useIsDesktop } from "@/lib/hooks/use-media-query";
import { useTranslation } from "@/lib/hooks/use-translation";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FileText, StickyNote, MessageSquare } from "lucide-react";

export type ContextMode = "off" | "insights" | "full";

export interface ContextSelections {
  sources: Record<string, ContextMode>;
  notes: Record<string, ContextMode>;
}

export default function NotebookPage() {
  const { t } = useTranslation();
  const params = useParams();

  // Ensure the notebook ID is properly decoded from URL
  const notebookId = params?.id ? decodeURIComponent(params.id as string) : "";

  const { data: notebook, isLoading: notebookLoading } =
    useNotebook(notebookId);
  const {
    sources,
    isLoading: sourcesLoading,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId);
  const { data: notes, isLoading: notesLoading } = useNotes(notebookId);

  // Get collapse states for dynamic layout
  const { notesCollapsed } = useNotebookColumnsStore();

  // Detect desktop to avoid double-mounting ChatColumn
  const isDesktop = useIsDesktop();

  // Mobile tab state (Sources, Notes, or Chat)
  const [mobileActiveTab, setMobileActiveTab] = useState<
    "sources" | "notes" | "chat"
  >("chat");

  // Sources are hidden by default in the immersive view; the "Edit sources"
  // button in the header opens this panel to manage / pick sources.
  const [sourcesDialogOpen, setSourcesDialogOpen] = useState(false);

  // Context selection state
  const [contextSelections, setContextSelections] = useState<ContextSelections>(
    {
      sources: {},
      notes: {},
    },
  );

  // Initialize and update selections when sources load or change
  useEffect(() => {
    if (sources && sources.length > 0) {
      setContextSelections((prev) => {
        const newSourceSelections = { ...prev.sources };
        sources.forEach((source) => {
          const currentMode = newSourceSelections[source.id];
          const hasInsights = source.insights_count > 0;

          if (currentMode === undefined) {
            // Initial setup - default based on insights availability
            newSourceSelections[source.id] = hasInsights ? "insights" : "full";
          } else if (currentMode === "full" && hasInsights) {
            // Source gained insights while in 'full' mode - auto-switch to 'insights'
            newSourceSelections[source.id] = "insights";
          }
        });
        return { ...prev, sources: newSourceSelections };
      });
    }
  }, [sources]);

  useEffect(() => {
    if (notes && notes.length > 0) {
      setContextSelections((prev) => {
        const newNoteSelections = { ...prev.notes };
        notes.forEach((note) => {
          // Only set default if not already set
          if (!(note.id in newNoteSelections)) {
            // Notes default to 'full'
            newNoteSelections[note.id] = "full";
          }
        });
        return { ...prev, notes: newNoteSelections };
      });
    }
  }, [notes]);

  // Navy corpus document selection state
  const { data: navyData } = useNavyDocuments();
  const [selectedNavyDocIds, setSelectedNavyDocIds] = useState<Set<string>>(
    new Set(),
  );
  const [navyDocsInitialized, setNavyDocsInitialized] = useState(false);

  // Persist navy doc selections per-notebook in localStorage so the
  // user's toggled choices survive page reloads / re-navigation.
  const navySelectionStorageKey = notebookId
    ? `notebook:${notebookId}:selectedNavyDocIds`
    : "";

  // Initialize from localStorage (if anything was saved before). We only
  // restore IDs that still exist in the current navy corpus to avoid
  // stale references.
  useEffect(() => {
    if (
      navyData?.documents &&
      navyData.documents.length > 0 &&
      !navyDocsInitialized &&
      navySelectionStorageKey
    ) {
      let restored: Set<string> = new Set();
      try {
        const raw = localStorage.getItem(navySelectionStorageKey);
        if (raw) {
          const parsed = JSON.parse(raw) as string[];
          if (Array.isArray(parsed)) {
            const valid = new Set(navyData.documents.map((d) => d.doc_id));
            restored = new Set(parsed.filter((id) => valid.has(id)));
            // Honour the 15-doc cap even on restore.
            if (restored.size > 15) {
              restored = new Set(Array.from(restored).slice(0, 15));
            }
          }
        }
      } catch {
        // Ignore malformed payload; start empty.
      }
      setSelectedNavyDocIds(restored);
      setNavyDocsInitialized(true);
    }
  }, [navyData, navyDocsInitialized, navySelectionStorageKey]);

  // Save selection changes back to localStorage once we've initialized
  // so we don't overwrite stored values with the empty default.
  useEffect(() => {
    if (!navyDocsInitialized || !navySelectionStorageKey) return;
    try {
      localStorage.setItem(
        navySelectionStorageKey,
        JSON.stringify(Array.from(selectedNavyDocIds)),
      );
    } catch {
      // localStorage may be unavailable (private mode); ignore.
    }
  }, [selectedNavyDocIds, navyDocsInitialized, navySelectionStorageKey]);

  const handleNavyDocSelectionChange = useCallback(
    (docId: string, selected: boolean) => {
      setSelectedNavyDocIds((prev) => {
        const next = new Set(prev);
        if (selected) {
          if (next.size >= 15) return prev; // enforce max 15
          next.add(docId);
        } else {
          next.delete(docId);
        }
        return next;
      });
    },
    [],
  );

  const handleNavySelectAll = useCallback(
    (selected: boolean) => {
      if (selected && navyData?.documents) {
        // Only select up to 15
        const ids = navyData.documents.slice(0, 15).map((d) => d.doc_id);
        setSelectedNavyDocIds(new Set(ids));
      } else {
        setSelectedNavyDocIds(new Set());
      }
    },
    [navyData],
  );

  // Handler to update context selection
  const handleContextModeChange = (
    itemId: string,
    mode: ContextMode,
    type: "source" | "note",
  ) => {
    setContextSelections((prev) => ({
      ...prev,
      [type === "source" ? "sources" : "notes"]: {
        ...(type === "source" ? prev.sources : prev.notes),
        [itemId]: mode,
      },
    }));
  };

  if (notebookLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!notebook) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">{t.notebooks.notFound}</h1>
        <p className="text-muted-foreground">{t.notebooks.notFoundDesc}</p>
      </div>
    );
  }

  return (
    // h-full is critical here: our parent in AppShell is `flex-1 overflow-auto`
    // (not a flex container), so `flex-1` on this root would NOT resolve to a
    // real height. Without an explicit height the inner grid row would grow
    // with its content — which is exactly what made the Sources/Notes/Chat
    // boxes resize when the Knowledge Base panel expanded/collapsed.
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-shrink-0 p-6 pb-0">
        <NotebookHeader
          notebook={notebook}
          onEditSources={() => setSourcesDialogOpen(true)}
        />
      </div>

      <div className="flex-1 min-h-0 p-6 pt-6 overflow-hidden flex flex-col">
        {/* Mobile: Tabbed interface - only render on mobile to avoid double-mounting */}
        {!isDesktop && (
          <>
            <div className="lg:hidden mb-4">
              <Tabs
                value={mobileActiveTab}
                onValueChange={(value) =>
                  setMobileActiveTab(value as "sources" | "notes" | "chat")
                }
              >
                <TabsList className="grid w-full grid-cols-3">
                  <TabsTrigger value="sources" className="gap-2">
                    <FileText className="h-4 w-4" />
                    {t.navigation.sources}
                  </TabsTrigger>
                  <TabsTrigger value="notes" className="gap-2">
                    <StickyNote className="h-4 w-4" />
                    {t.notebooks.agentNotes}
                  </TabsTrigger>
                  <TabsTrigger value="chat" className="gap-2">
                    <MessageSquare className="h-4 w-4" />
                    {t.common.chat}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </div>

            {/* Mobile: Show only active tab */}
            <div className="flex-1 overflow-hidden lg:hidden">
              {mobileActiveTab === "sources" && (
                <SourcesColumn
                  sources={sources}
                  isLoading={sourcesLoading}
                  notebookId={notebookId}
                  notebookName={notebook?.name}
                  onRefresh={refetchSources}
                  contextSelections={contextSelections.sources}
                  onContextModeChange={(sourceId, mode) =>
                    handleContextModeChange(sourceId, mode, "source")
                  }
                  hasNextPage={hasNextPage}
                  isFetchingNextPage={isFetchingNextPage}
                  fetchNextPage={fetchNextPage}
                  selectedNavyDocIds={selectedNavyDocIds}
                  onNavyDocSelectionChange={handleNavyDocSelectionChange}
                  onNavyDocSelectAll={handleNavySelectAll}
                />
              )}
              {mobileActiveTab === "notes" && (
                <NotesColumn
                  notes={notes}
                  isLoading={notesLoading}
                  notebookId={notebookId}
                  contextSelections={contextSelections.notes}
                  onContextModeChange={(noteId, mode) =>
                    handleContextModeChange(noteId, mode, "note")
                  }
                />
              )}
              {mobileActiveTab === "chat" && (
                <ChatColumn
                  notebookId={notebookId}
                  contextSelections={contextSelections}
                  sources={sources}
                  sourcesLoading={sourcesLoading}
                  selectedNavyDocIds={selectedNavyDocIds}
                />
              )}
            </div>
          </>
        )}

        {/* Desktop: Chat-predominant layout (NotebookLM-style).
            Sources are no longer a persistent column — they live behind the
            "Edit sources" button. The remaining columns are the Chat (wide)
            and the Agent Collaboration / Notes panel (thin, collapsible). */}
        <div className="hidden lg:flex h-full min-h-0 gap-4">
          {/* Chat Column — predominant, takes remaining space */}
          <div className="h-full min-h-0 min-w-0 overflow-hidden flex-1">
            <ChatColumn
              notebookId={notebookId}
              contextSelections={contextSelections}
              sources={sources}
              sourcesLoading={sourcesLoading}
              selectedNavyDocIds={selectedNavyDocIds}
            />
          </div>

          {/* Agent Collaboration (Notes) — thinner side panel */}
          <div
            className={cn(
              "h-full min-h-0 overflow-hidden transition-all duration-150 flex-shrink-0",
              notesCollapsed ? "w-12" : "w-80",
            )}
          >
            <NotesColumn
              notes={notes}
              isLoading={notesLoading}
              notebookId={notebookId}
              contextSelections={contextSelections.notes}
              onContextModeChange={(noteId, mode) =>
                handleContextModeChange(noteId, mode, "note")
              }
            />
          </div>
        </div>
      </div>

      {/* Edit sources — hidden by default, opened from the header button. */}
      <Dialog open={sourcesDialogOpen} onOpenChange={setSourcesDialogOpen}>
        <DialogContent className="max-w-3xl h-[80vh] flex flex-col p-0">
          <DialogHeader className="px-6 pt-6 pb-0">
            <DialogTitle>{t.notebooks.editSources}</DialogTitle>
          </DialogHeader>
          <div className="flex-1 min-h-0 overflow-hidden px-6 pb-6 pt-2">
            <SourcesColumn
              embedded
              sources={sources}
              isLoading={sourcesLoading}
              notebookId={notebookId}
              notebookName={notebook?.name}
              onRefresh={refetchSources}
              contextSelections={contextSelections.sources}
              onContextModeChange={(sourceId, mode) =>
                handleContextModeChange(sourceId, mode, "source")
              }
              hasNextPage={hasNextPage}
              isFetchingNextPage={isFetchingNextPage}
              fetchNextPage={fetchNextPage}
              selectedNavyDocIds={selectedNavyDocIds}
              onNavyDocSelectionChange={handleNavyDocSelectionChange}
              onNavyDocSelectAll={handleNavySelectAll}
            />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
