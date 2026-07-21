// Builds a short, human-readable summary of the source context that fed a chat
// turn, shown as a collapsible note above the assistant's answer so the user can
// "see the context" that informed it. Deterministic and extractive (no LLM call,
// no hallucinated claims): it lists the sources/notes used and appends a brief
// gist taken verbatim from the most substantial excerpt.

interface StructuredContextItem {
  title?: unknown
  id?: unknown
  content?: unknown
  full_text?: unknown
  visual_content?: unknown
  caption?: unknown
}

interface StructuredContext {
  sources?: StructuredContextItem[]
  notes?: StructuredContextItem[]
  navy_corpus?: StructuredContextItem[]
}

export interface ContextSummaryLabels {
  // e.g. "Based on {sources}" — {sources} is replaced with the joined list.
  based_on: string
  source: string
  sources: string
  note: string
  notes: string
  document: string
  documents: string
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function itemTitle(item: StructuredContextItem): string {
  return asText(item.title) || asText(item.id) || ''
}

function itemContent(item: StructuredContextItem): string {
  return (
    asText(item.content) ||
    asText(item.full_text) ||
    asText(item.visual_content) ||
    asText(item.caption)
  )
}

function pluralLabel(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`
}

function extractiveGist(text: string, maxChars = 220): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (clean.length <= maxChars) return clean
  const slice = clean.slice(0, maxChars)
  // Prefer to cut on a sentence boundary so the gist reads as a whole thought.
  const lastStop = Math.max(
    slice.lastIndexOf('. '),
    slice.lastIndexOf('! '),
    slice.lastIndexOf('? '),
  )
  const cut = lastStop > 80 ? slice.slice(0, lastStop + 1) : slice
  return `${cut.trim()}…`
}

/**
 * Returns a 1-2 sentence summary of the context, or undefined when no context
 * with usable content was provided (so the caller can skip the affordance).
 */
export function buildContextSummary(
  context: StructuredContext | null | undefined,
  labels: ContextSummaryLabels,
): string | undefined {
  if (!context) return undefined

  const sources = (context.sources ?? []).filter((i) => itemContent(i).trim())
  const notes = (context.notes ?? []).filter((i) => itemContent(i).trim())
  const navy = (context.navy_corpus ?? []).filter((i) => itemContent(i).trim())

  const totalItems = sources.length + notes.length + navy.length
  if (totalItems === 0) return undefined

  const groups: string[] = []
  if (sources.length) groups.push(pluralLabel(sources.length, labels.source, labels.sources))
  if (notes.length) groups.push(pluralLabel(notes.length, labels.note, labels.notes))
  if (navy.length) groups.push(pluralLabel(navy.length, labels.document, labels.documents))

  const titles = [...sources, ...notes, ...navy]
    .map(itemTitle)
    .filter(Boolean)
    .slice(0, 4)
    .map((title) => `«${title}»`)

  const parts: string[] = []
  const header = labels.based_on.replace('{sources}', groups.join(', '))
  parts.push(titles.length ? `${header}: ${titles.join(', ')}.` : `${header}.`)

  // Add a short extractive gist from the longest excerpt so the note conveys a
  // sense of the content, not just the titles.
  const longest = [...sources, ...notes, ...navy]
    .map(itemContent)
    .sort((a, b) => b.length - a.length)[0]
  if (longest) {
    const gist = extractiveGist(longest)
    if (gist) parts.push(gist)
  }

  return parts.join(' ')
}
