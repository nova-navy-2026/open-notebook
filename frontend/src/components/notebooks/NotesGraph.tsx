"use client";

import { useMemo, useState } from "react";
import { useNotes } from "@/lib/hooks/use-notes";
import { useTopics } from "@/lib/hooks/use-navy-docs";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Loader2, StickyNote, AlertCircle, Info } from "lucide-react";
import { useTranslation } from "@/lib/hooks/use-translation";
import { GraphCanvas } from "./GraphCanvas";
import { buildNotesGraph, type NotesGraphMode } from "./graph-utils";

interface NotesGraphProps {
  notebookId: string;
  className?: string;
}

/**
 * Notes visualization: bipartite (notes clustered by topic via keyword
 * heuristic) or a note-similarity network (cosine similarity on note text).
 * Mirrors the two modes available in <DocumentGraph> for sources.
 */
export function NotesGraph({ notebookId, className }: NotesGraphProps) {
  const { t } = useTranslation();
  const { data: notes, isLoading: notesLoading, error: notesError } =
    useNotes(notebookId);
  const { data: topics, isLoading: topicsLoading, error: topicsError } =
    useTopics();

  const [mode, setMode] = useState<NotesGraphMode>("bipartite");
  const [threshold, setThreshold] = useState(0.1);

  const isLoading = notesLoading || topicsLoading;
  const error = notesError || topicsError;

  const unclassifiedLabel = t.navyDocs?.unclassified ?? "Unclassified";
  const built = useMemo(
    () =>
      notes && topics
        ? buildNotesGraph(notes, topics, mode, threshold, { unclassifiedLabel })
        : null,
    [notes, topics, mode, threshold, unclassifiedLabel],
  );
  const graphData = useMemo(
    () => ({ nodes: built?.nodes ?? [], links: built?.links ?? [] }),
    [built],
  );

  // Reheat when the underlying notes set changes or mode switches, but NOT on
  // threshold change (that only adds/removes similarity links).
  const reheatKey = useMemo(
    () =>
      `${mode}:` +
      (notes ?? []).map((n) => `${n.id}:${n.updated}`).sort().join("|"),
    [mode, notes],
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[200px] text-sm text-muted-foreground gap-2">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t.navyDocs?.notesGraphLoading ?? "Building note relationships..."}
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center justify-center h-full min-h-[200px] text-sm text-destructive gap-2">
        <AlertCircle className="h-4 w-4" />
        {t.navyDocs?.notesGraphError ?? "Failed to build the notes graph."}
      </div>
    );
  }
  if (!notes || notes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-sm text-muted-foreground gap-2 text-center px-4">
        <StickyNote className="h-6 w-6" />
        {t.navyDocs?.notesGraphEmpty ??
          "No notes to visualize yet. Add notes to this notebook to see how they relate to topics."}
      </div>
    );
  }

  const matchedNotes = graphData.nodes.filter((n) => n.kind === "note").length;
  const topicCount = built?.legend.filter((l) => l.id !== "__none__").length ?? 0;
  const heuristicHint =
    t.navyDocs?.notesGraphHeuristicHint ??
    "Topics are inferred from note text by keyword matching — a rough heuristic, not semantic classification.";

  return (
    <div className={`flex flex-col gap-2 h-full min-h-0 ${className ?? ""}`}>
      {/* Controls — kept to a single non-wrapping row so the toggles in the
          split view line up with the Sources graph. */}
      <div className="flex items-center gap-2 min-w-0">
        <Tabs value={mode} onValueChange={(v) => setMode(v as NotesGraphMode)}>
          <TabsList className="h-7">
            <TabsTrigger
              value="bipartite"
              className="whitespace-nowrap px-2 text-[11px]"
            >
              {t.navyDocs?.notesModeBipartite ?? "Notes ↔ Topics"}
            </TabsTrigger>
            <TabsTrigger
              value="similarity"
              className="whitespace-nowrap px-2 text-[11px]"
            >
              {t.navyDocs?.notesModeSimilarity ?? "Note similarity"}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <span
          title={heuristicHint}
          aria-label={heuristicHint}
          className="shrink-0 text-muted-foreground/70 hover:text-muted-foreground"
        >
          <Info className="h-3.5 w-3.5" />
        </span>

        <div className="flex-1" />
        <Badge variant="secondary" className="shrink-0 text-[11px]">
          {matchedNotes} {t.navyDocs?.notesLabel ?? "notes"} · {topicCount}{" "}
          {t.navyDocs?.graphTopicsLabel ?? "topics"}
        </Badge>
      </div>

      {/* Reserve the slider row in both modes so split columns keep equal
          canvas heights regardless of the selected mode. */}
      <div className="flex h-6 items-center gap-2 text-xs text-muted-foreground">
        {mode === "similarity" && (
          <>
            <span className="shrink-0">
              {t.navyDocs?.graphThreshold ?? "Min. similarity"}
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="flex-1 accent-primary"
            />
            <span className="tabular-nums w-8 shrink-0">
              {threshold.toFixed(2)}
            </span>
          </>
        )}
      </div>

      <GraphCanvas
        className="flex-1"
        graphData={graphData}
        legend={built?.legend ?? []}
        reheatKey={reheatKey}
        linkDistance={mode === "bipartite" ? 80 : 140}
      />
    </div>
  );
}
