"use client";

import { useMemo, useState } from "react";
import { useDocumentGraph } from "@/lib/hooks/use-navy-docs";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Loader2, Network, AlertCircle } from "lucide-react";
import { useTranslation } from "@/lib/hooks/use-translation";
import { GraphCanvas } from "./GraphCanvas";
import { buildDocumentGraph, type GraphMode } from "./graph-utils";

interface DocumentGraphProps {
  docIds: string[];
  className?: string;
}

/**
 * Sources visualization: documents clustered into the topic taxonomy
 * (bipartite) or a document-similarity network. Owns its controls and delegates
 * the force-directed rendering to <GraphCanvas>.
 */
export function DocumentGraph({ docIds, className }: DocumentGraphProps) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useDocumentGraph(docIds);
  const [mode, setMode] = useState<GraphMode>("bipartite");
  const [threshold, setThreshold] = useState(0.1);

  const built = useMemo(
    () => (data ? buildDocumentGraph(data, mode, threshold) : null),
    [data, mode, threshold],
  );
  const graphData = useMemo(
    () => ({ nodes: built?.nodes ?? [], links: built?.links ?? [] }),
    [built],
  );

  // Reheat the layout on mode/selection change — but NOT on threshold change
  // (that only adds/removes similarity links).
  const reheatKey = useMemo(
    () => `${mode}:${[...docIds].sort().join(",")}`,
    [mode, docIds],
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[200px] text-sm text-muted-foreground gap-2">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t.navyDocs?.graphLoading ?? "Building document relationships..."}
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center justify-center h-full min-h-[200px] text-sm text-destructive gap-2">
        <AlertCircle className="h-4 w-4" />
        {t.navyDocs?.graphError ?? "Failed to build the document graph."}
      </div>
    );
  }
  if (!data || data.documents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-sm text-muted-foreground gap-2 text-center px-4">
        <Network className="h-6 w-6" />
        {t.navyDocs?.graphEmpty ??
          "No classified documents to display. Select documents and run topic classification."}
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-2 h-full min-h-0 ${className ?? ""}`}>
      {/* Controls — single non-wrapping row so the toggles line up with the
          Notes graph in the split view. */}
      <div className="flex items-center gap-2 min-w-0">
        <Tabs value={mode} onValueChange={(v) => setMode(v as GraphMode)}>
          <TabsList className="h-7">
            <TabsTrigger
              value="bipartite"
              className="whitespace-nowrap px-2 text-[11px]"
            >
              {t.navyDocs?.graphModeBipartite ?? "Documents ↔ Topics"}
            </TabsTrigger>
            <TabsTrigger
              value="similarity"
              className="whitespace-nowrap px-2 text-[11px]"
            >
              {t.navyDocs?.graphModeSimilarity ?? "Document similarity"}
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="flex-1" />
        <Badge variant="secondary" className="shrink-0 text-[11px]">
          {data.documents.length} {t.navyDocs?.graphDocsLabel ?? "docs"} ·{" "}
          {data.topics.length} {t.navyDocs?.graphTopicsLabel ?? "topics"}
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
