"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import { NotebookHeader } from "../components/NotebookHeader";
import { SourcesColumn } from "../components/SourcesColumn";
import { NotesColumn } from "../components/NotesColumn";
import { ChatColumn } from "../components/ChatColumn";
import { useNotebook, useUpdateNavyDocs } from "@/lib/hooks/use-notebooks";
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
  // Collaborative notebooks poll their shared sources/notes so members stay in
  // sync without manual refreshes.
  const isCollaborative = !!notebook?.collaborative;
  // Only the notebook owner may remove/delete sources from a shared notebook.
  // Private notebooks are always owned by the viewer, so this defaults to true.
  const isNotebookOwner = notebook?.is_owner ?? true;
  const {
    sources,
    isLoading: sourcesLoading,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId, isCollaborative);
  const { data: notes, isLoading: notesLoading } = useNotes(
    notebookId,
    isCollaborative,
  );

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

  // Navy corpus document selection state.
  //
  // Persistence depends on the notebook type:
  // - Collaborative notebooks store the selection server-side (on the notebook
  //   record) so every member shares one selection and the agents stay
  //   consistent. Polling (useNotebook) refreshes another member's changes.
  // - Private notebooks keep the selection in browser localStorage (no extra
  //   network, survives reloads on the same device).
  const { data: navyData } = useNavyDocuments();
  const updateNavyDocs = useUpdateNavyDocs();
  const [selectedNavyDocIds, setSelectedNavyDocIds] = useState<Set<string>>(
    new Set(),
  );
  const [navyDocsInitialized, setNavyDocsInitialized] = useState(false);
  // Serialized (sorted) form of the selection we last reconciled with the
  // persistence layer. Lets us distinguish our own writes from genuine remote
  // changes so server polling doesn't fight local edits (and vice-versa).
  const lastSyncedNavyRef = useRef<string>("");

  const navySelectionStorageKey = notebookId
    ? `notebook:${notebookId}:selectedNavyDocIds`
    : "";

  const serializeIds = (ids: Iterable<string>) =>
    JSON.stringify(Array.from(ids).sort());

  // Initialize the selection once the corpus and notebook have loaded.
  useEffect(() => {
    if (navyDocsInitialized) return;
    if (!navyData?.documents || navyData.documents.length === 0) return;
    if (!notebook) return;

    const valid = new Set(navyData.documents.map((d) => d.doc_id));
    const readLocal = (): Set<string> => {
      if (!navySelectionStorageKey) return new Set();
      try {
        const raw = localStorage.getItem(navySelectionStorageKey);
        if (raw) {
          const parsed = JSON.parse(raw) as string[];
          if (Array.isArray(parsed)) {
            return new Set(parsed.filter((id) => valid.has(id)));
          }
        }
      } catch {
        // Ignore malformed payload.
      }
      return new Set();
    };

    let restored: Set<string> = new Set();
    // The baseline is what we consider already persisted. When it differs from
    // `restored`, the persist effect pushes the difference (used to seed the
    // server from a pre-share localStorage selection).
    let baseline: Set<string> = new Set();

    if (isCollaborative) {
      const serverIds = (notebook.navy_doc_ids ?? []).filter((id) =>
        valid.has(id),
      );
      if (serverIds.length > 0) {
        // Server is the source of truth.
        restored = new Set(serverIds);
        baseline = new Set(serverIds);
      } else {
        // Server has no selection yet: if this browser still holds a selection
        // from before the notebook was shared, adopt and seed it to the server
        // so all members inherit the owner's choices.
        restored = readLocal();
        baseline = new Set(); // empty server → persist effect will seed it
      }
    } else {
      restored = readLocal();
      baseline = new Set(restored); // already in localStorage; nothing to write
    }

    // Honour the 15-doc cap even on restore.
    if (restored.size > 15) {
      restored = new Set(Array.from(restored).slice(0, 15));
    }
    setSelectedNavyDocIds(restored);
    lastSyncedNavyRef.current = serializeIds(baseline);
    setNavyDocsInitialized(true);
  }, [
    navyData,
    notebook,
    isCollaborative,
    navyDocsInitialized,
    navySelectionStorageKey,
  ]);

  // Persist selection changes once initialized.
  useEffect(() => {
    if (!navyDocsInitialized) return;
    const serialized = serializeIds(selectedNavyDocIds);
    // Nothing actually changed relative to what we last reconciled.
    if (serialized === lastSyncedNavyRef.current) return;

    if (isCollaborative) {
      if (!notebookId) return;
      lastSyncedNavyRef.current = serialized;
      updateNavyDocs.mutate({
        id: notebookId,
        docIds: Array.from(selectedNavyDocIds),
      });
    } else if (navySelectionStorageKey) {
      lastSyncedNavyRef.current = serialized;
      try {
        localStorage.setItem(
          navySelectionStorageKey,
          JSON.stringify(Array.from(selectedNavyDocIds)),
        );
      } catch {
        // localStorage may be unavailable (private mode); ignore.
      }
    }
    // updateNavyDocs is intentionally omitted: the mutation object identity
    // changes every render and would re-run this effect spuriously.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedNavyDocIds,
    navyDocsInitialized,
    isCollaborative,
    notebookId,
    navySelectionStorageKey,
  ]);

  // Collaborative notebooks: adopt a remote selection change (from polling)
  // when it differs from what we last reconciled. Skipped for our own writes
  // because those update lastSyncedNavyRef first.
  useEffect(() => {
    if (!navyDocsInitialized || !isCollaborative) return;
    if (!notebook || !navyData?.documents) return;
    const valid = new Set(navyData.documents.map((d) => d.doc_id));
    const serverIds = (notebook.navy_doc_ids ?? []).filter((id) =>
      valid.has(id),
    );
    const serverSerialized = serializeIds(serverIds);
    if (serverSerialized === lastSyncedNavyRef.current) return;
    lastSyncedNavyRef.current = serverSerialized;
    setSelectedNavyDocIds(new Set(serverIds));
  }, [notebook, navyData, navyDocsInitialized, isCollaborative]);

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
                  isNotebookOwner={isNotebookOwner}
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
              notesCollapsed ? "w-12" : "w-80 xl:w-96 2xl:w-[26rem]",
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
              isNotebookOwner={isNotebookOwner}
            />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
