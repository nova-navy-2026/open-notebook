// Shared shapes, colour helpers, and graph builders for the document/notes
// relationship visualizations. The presentational <GraphCanvas> consumes the
// {nodes, links} produced here; each view (sources, notes) owns its own
// builder so the canvas stays agnostic about where the data came from.

import type {
  DocumentGraphResponse,
  GraphDocumentNode,
  TopicClass,
} from "@/lib/api/navy-docs";
import type { NoteResponse } from "@/lib/types/api";

export const NEUTRAL = "#94a3b8";
export const DOC_DEFAULT = "#64748b";
export const NO_CLUSTER = "__none__";
export const MIN_HEIGHT = 320;
export const BG = "#f8fafc";

export type GraphMode = "bipartite" | "similarity";
export type NotesGraphMode = "bipartite" | "similarity";

// A row in the selected-node detail overlay (e.g. a class + its chunk count,
// or a matched topic + its keyword-hit score).
export interface DetailRow {
  label: string;
  value?: string | number;
}

// Internal node/link shapes fed to the force graph. `ax`/`ay` are the cluster
// anchor coordinates the positional forces pull each node toward, so every
// topic (and the documents/notes it dominates) settles into its own region.
export interface GNode {
  id: string;
  kind: "doc" | "topic" | "note";
  label: string;
  color: string;
  val: number;
  clusterId: string;
  ax: number;
  ay: number;
  // Generic detail surfaced in the overlay so the canvas need not know about
  // domain types. Builders fill whichever fields make sense.
  detailText?: string;
  detailRows?: DetailRow[];
  // Mutated by the simulation.
  x?: number;
  y?: number;
}

export interface GLink {
  source: string;
  target: string;
  width: number;
  color: string;
}

// A topic entry for the canvas legend.
export interface LegendTopic {
  id: string;
  label: string;
  color: string;
  count?: number;
}

export interface BuiltGraph {
  nodes: GNode[];
  links: GLink[];
  legend: LegendTopic[];
}

/** "#rrggbb" → "rgba(r,g,b,a)" so links/bubbles can be softened. */
export function withAlpha(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const full =
    h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  if ([r, g, b].some(Number.isNaN)) return `rgba(148,163,184,${a})`;
  return `rgba(${r},${g},${b},${a})`;
}

/**
 * Anchor each topic on a ring, sizing the ring by the busiest cluster so the
 * colored bubbles never overlap. Returns a map of topic id → anchor point;
 * shared by both the documents and notes builders.
 */
function computeAnchors(
  topicIds: string[],
  counts: Map<string, number>,
): Map<string, { x: number; y: number }> {
  const T = topicIds.length;
  const maxCount = Math.max(1, ...counts.values());
  // Generous spacing so clusters read as distinct islands spread across the
  // (now full-window) canvas rather than a tight central knot.
  const blobR = Math.sqrt(maxCount) * 26 + 60;
  const ringR = T <= 1 ? 0 : Math.max(360, (blobR * T) / Math.PI);
  const anchor = new Map<string, { x: number; y: number }>();
  topicIds.forEach((id, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, T);
    anchor.set(id, { x: ringR * Math.cos(angle), y: ringR * Math.sin(angle) });
  });
  return anchor;
}

/** The class with the most chunks for a document (its cluster), or null. */
export function dominantClass(doc: GraphDocumentNode): string | null {
  let best: { cls: string; count: number } | null = null;
  for (const c of doc.classes) {
    if (!best || c.count > best.count) best = { cls: c.class, count: c.count };
  }
  return best ? best.cls : null;
}

// --- Sources: documents ↔ topics / document similarity ----------------------

export function buildDocumentGraph(
  data: DocumentGraphResponse,
  mode: GraphMode,
  threshold: number,
): BuiltGraph {
  const topicColors = new Map(data.topics.map((t) => [t.id, t.color]));

  const counts = new Map<string, number>();
  for (const d of data.documents) {
    const cls = dominantClass(d) ?? NO_CLUSTER;
    counts.set(cls, (counts.get(cls) ?? 0) + 1);
  }
  const anchor = computeAnchors(
    data.topics.map((t) => t.id),
    counts,
  );
  const anchorFor = (cls: string | null) =>
    (cls && anchor.get(cls)) || { x: 0, y: 0 };

  const docNodes: GNode[] = data.documents.map((d) => {
    const cls = dominantClass(d);
    const a = anchorFor(cls);
    return {
      id: `doc:${d.id}`,
      kind: "doc",
      label: d.label,
      color: cls ? (topicColors.get(cls) ?? DOC_DEFAULT) : DOC_DEFAULT,
      val: Math.max(2.5, Math.sqrt(d.chunk_count || 1) * 2),
      clusterId: cls ?? NO_CLUSTER,
      ax: a.x,
      ay: a.y,
      detailRows: d.classes.map((c) => ({ label: c.class, value: c.count })),
    };
  });

  const legend: LegendTopic[] = data.topics.map((t) => ({
    id: t.id,
    label: t.label,
    color: t.color,
    count: t.doc_count,
  }));

  if (mode === "bipartite") {
    const topicNodes: GNode[] = data.topics.map((t) => {
      const a = anchorFor(t.id);
      return {
        id: `topic:${t.id}`,
        kind: "topic",
        label: t.label,
        color: t.color,
        val: Math.max(7, Math.sqrt(t.chunk_count || 1) * 2.5),
        clusterId: t.id,
        ax: a.x,
        ay: a.y,
        detailText: `${t.doc_count} docs · ${t.chunk_count} chunks`,
      };
    });
    const links: GLink[] = data.edges_bipartite.map((e) => ({
      source: `doc:${e.source}`,
      target: `topic:${e.topic}`,
      width: Math.max(0.6, Math.min(6, Math.sqrt(e.weight))),
      color: withAlpha(topicColors.get(e.topic) ?? NEUTRAL, 0.4),
    }));
    return { nodes: [...docNodes, ...topicNodes], links, legend };
  }

  // similarity: document↔document edges above the threshold
  const links: GLink[] = data.edges_similarity
    .filter((e) => e.weight >= threshold)
    .map((e) => ({
      source: `doc:${e.source}`,
      target: `doc:${e.target}`,
      width: Math.max(0.6, e.weight * 6),
      color: withAlpha(NEUTRAL, 0.25 + e.weight * 0.5),
    }));
  return { nodes: docNodes, links, legend };
}

// --- Notes: notes ↔ topics (client-side keyword heuristic) ------------------

// Tiny stop-list so common label filler words don't drive matches.
const STOP = new Set([
  "and",
  "the",
  "for",
  "with",
  "of",
  "to",
  "in",
  "on",
  "a",
  "an",
  "general",
  "other",
  "misc",
]);

/** Split a topic label into lowercase keyword tokens worth matching on. */
function topicKeywords(label: string): string[] {
  return label
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length >= 3 && !STOP.has(w));
}

/** Count non-overlapping whole-word occurrences of `word` in `text`. */
function wordHits(text: string, word: string): number {
  let count = 0;
  let from = 0;
  for (;;) {
    const idx = text.indexOf(word, from);
    if (idx === -1) break;
    const before = idx === 0 ? " " : text[idx - 1];
    const afterIdx = idx + word.length;
    const after = afterIdx >= text.length ? " " : text[afterIdx];
    // Loose word boundary: surrounding char is not a letter/digit.
    if (!/[a-z0-9]/.test(before) && !/[a-z0-9]/.test(after)) count++;
    from = idx + word.length;
  }
  return count;
}

interface NoteTopicScore {
  topic: TopicClass;
  score: number;
}

/**
 * Score a single note against every topic by counting keyword hits in its
 * title + content. Returns matches (score > 0) sorted strongest-first.
 */
function scoreNote(
  note: NoteResponse,
  topics: TopicClass[],
  keywords: Map<string, string[]>,
): NoteTopicScore[] {
  const text = `${note.title ?? ""} ${note.content ?? ""}`.toLowerCase();
  const scores: NoteTopicScore[] = [];
  for (const topic of topics) {
    let score = 0;
    for (const kw of keywords.get(topic.id) ?? []) {
      score += wordHits(text, kw);
    }
    if (score > 0) scores.push({ topic, score });
  }
  scores.sort((a, b) => b.score - a.score);
  return scores;
}

/** Bag-of-words token frequencies for a note, reusing the same stop-list. */
function tokenizeNote(note: NoteResponse): Map<string, number> {
  const text = `${note.title ?? ""} ${note.content ?? ""}`.toLowerCase();
  const freq = new Map<string, number>();
  for (const w of text.split(/[^a-z0-9]+/)) {
    if (w.length >= 3 && !STOP.has(w)) freq.set(w, (freq.get(w) ?? 0) + 1);
  }
  return freq;
}

/** Cosine similarity between two term-frequency vectors. */
function cosineSim(a: Map<string, number>, b: Map<string, number>): number {
  let dot = 0, magA = 0, magB = 0;
  for (const [w, fa] of a) {
    dot += fa * (b.get(w) ?? 0);
    magA += fa * fa;
  }
  for (const [, fb] of b) magB += fb * fb;
  return magA && magB ? dot / (Math.sqrt(magA) * Math.sqrt(magB)) : 0;
}

export function buildNotesGraph(
  notes: NoteResponse[],
  topics: TopicClass[],
  mode: NotesGraphMode,
  threshold: number,
  opts?: { unclassifiedLabel?: string },
): BuiltGraph {
  const unclassifiedLabel = opts?.unclassifiedLabel ?? "Unclassified";
  const keywords = new Map(topics.map((t) => [t.id, topicKeywords(t.label)]));

  // Score every note up-front so we know which topics actually appear.
  const scored = notes.map((note) => ({
    note,
    matches: scoreNote(note, topics, keywords),
  }));

  // Count notes per dominant topic to size the cluster ring.
  const dominantCounts = new Map<string, number>();
  for (const { matches } of scored) {
    const cls = matches[0]?.topic.id ?? NO_CLUSTER;
    dominantCounts.set(cls, (dominantCounts.get(cls) ?? 0) + 1);
  }

  // Only topics that own at least one note get a hub/anchor — mirrors the
  // sources graph, which never renders empty topic hubs.
  const usedTopicIds = new Set<string>();
  for (const { matches } of scored) {
    for (const m of matches) usedTopicIds.add(m.topic.id);
  }
  const usedTopics = topics.filter((t) => usedTopicIds.has(t.id));
  const topicColors = new Map(usedTopics.map((t) => [t.id, t.color]));

  const anchor = computeAnchors(
    usedTopics.map((t) => t.id),
    dominantCounts,
  );
  const anchorFor = (cls: string | null) =>
    (cls && anchor.get(cls)) || { x: 0, y: 0 };

  // Note nodes are shared between both modes; topic coloring retained in
  // similarity mode so the visual is consistent and readable.
  const noteNodes: GNode[] = scored.map(({ note, matches }) => {
    const dominant = matches[0]?.topic ?? null;
    const a = anchorFor(dominant?.id ?? null);
    const isAi = note.note_type === "ai";
    const label = note.title?.trim() || (note.content ?? "").slice(0, 40) || "Note";
    return {
      id: `note:${note.id}`,
      kind: "note",
      label,
      color: dominant ? (topicColors.get(dominant.id) ?? DOC_DEFAULT) : DOC_DEFAULT,
      val: 3.5,
      clusterId: dominant?.id ?? NO_CLUSTER,
      ax: a.x,
      ay: a.y,
      detailText: isAi ? "AI note" : "Human note",
      detailRows: matches.map((m) => ({ label: m.topic.label, value: m.score })),
    };
  });

  const noteCount = new Map<string, number>();
  for (const { matches } of scored) {
    for (const m of matches) {
      noteCount.set(m.topic.id, (noteCount.get(m.topic.id) ?? 0) + 1);
    }
  }

  const legend: LegendTopic[] = usedTopics.map((t) => ({
    id: t.id,
    label: t.label,
    color: t.color,
    count: noteCount.get(t.id) ?? 0,
  }));

  const unclassified = dominantCounts.get(NO_CLUSTER) ?? 0;
  if (unclassified > 0) {
    legend.push({
      id: NO_CLUSTER,
      label: unclassifiedLabel,
      color: DOC_DEFAULT,
      count: unclassified,
    });
  }

  if (mode === "bipartite") {
    // Topic hubs sized by how many notes they own.
    const topicNodes: GNode[] = usedTopics.map((t) => {
      const a = anchorFor(t.id);
      const n = noteCount.get(t.id) ?? 0;
      return {
        id: `topic:${t.id}`,
        kind: "topic",
        label: t.label,
        color: t.color,
        val: Math.max(7, Math.sqrt(n) * 4),
        clusterId: t.id,
        ax: a.x,
        ay: a.y,
        detailText: `${n} ${n === 1 ? "note" : "notes"}`,
      };
    });

    const links: GLink[] = [];
    for (const { note, matches } of scored) {
      for (const m of matches) {
        links.push({
          source: `note:${note.id}`,
          target: `topic:${m.topic.id}`,
          width: Math.max(0.6, Math.min(6, Math.sqrt(m.score))),
          color: withAlpha(topicColors.get(m.topic.id) ?? NEUTRAL, 0.4),
        });
      }
    }

    return { nodes: [...noteNodes, ...topicNodes], links, legend };
  }

  // similarity: note↔note edges above the cosine similarity threshold
  const vectors = scored.map(({ note, matches }) => {
    const dominant = matches[0]?.topic;
    return {
      id: note.id,
      dominantColor: dominant ? (topicColors.get(dominant.id) ?? NEUTRAL) : NEUTRAL,
      vec: tokenizeNote(note),
    };
  });

  const links: GLink[] = [];
  for (let i = 0; i < vectors.length; i++) {
    for (let j = i + 1; j < vectors.length; j++) {
      const sim = cosineSim(vectors[i].vec, vectors[j].vec);
      if (sim >= threshold) {
        links.push({
          source: `note:${vectors[i].id}`,
          target: `note:${vectors[j].id}`,
          width: Math.max(0.6, sim * 6),
          color: withAlpha(vectors[i].dominantColor, 0.25 + sim * 0.5),
        });
      }
    }
  }

  return { nodes: noteNodes, links, legend };
}
