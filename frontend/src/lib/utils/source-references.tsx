import React from 'react'
import { Anchor, FileText, Lightbulb, FileEdit } from 'lucide-react'

export type ReferenceType = 'source' | 'note' | 'source_insight' | 'navy'

/**
 * Navy citation refs are bracket-bounded because their ids are RAW FILENAMES
 * ("PEETNA 3253 - Logística I.pdf", "45255_panavsup 206 (a).pdf") — spaces,
 * accents, dots, hyphens, parentheses. A charset-based pattern cannot match
 * them. The payload is `{doc_id}` optionally followed by `:p{page}`/`:s{n}`.
 *
 * A bracket may hold several comma-separated refs (LLM edge case, same as the
 * source/note handling below), so navy refs are found in two steps: locate
 * bracket contents, then split items at commas that precede another known ref
 * prefix — a bare comma can legitimately appear inside a filename.
 */
const BRACKET_CONTENT_PATTERN = /\[([^\[\]\n]+)\]/g
const NAVY_ITEM_PATTERN =
  /(?<=^|[,\s])navy:(.+?)(?=\s*,\s*(?:source_insight|insight|note|source|navy):|$)/g

interface NavyRefMatch {
  /** Decoded payload: `{doc_id}(:p{N})?(:s{M})?` */
  payload: string
  /** Absolute index of `navy:` in the text */
  start: number
  /** Absolute index just past the payload */
  end: number
  /** True when the ref is the bracket's entire content (`[navy:X]`) */
  wholeBracket: boolean
}

function findNavyRefs(text: string): NavyRefMatch[] {
  const out: NavyRefMatch[] = []
  BRACKET_CONTENT_PATTERN.lastIndex = 0
  let bracket: RegExpExecArray | null
  while ((bracket = BRACKET_CONTENT_PATTERN.exec(text)) !== null) {
    const content = bracket[1]
    if (!content.includes('navy:')) continue
    const contentStart = bracket.index + 1
    NAVY_ITEM_PATTERN.lastIndex = 0
    let item: RegExpExecArray | null
    while ((item = NAVY_ITEM_PATTERN.exec(content)) !== null) {
      const payload = item[1].trim()
      if (!payload) continue
      out.push({
        payload,
        start: contentStart + item.index,
        end: contentStart + item.index + 'navy:'.length + item[1].length,
        wholeBracket: item.index === 0 && item[0].length === content.length,
      })
    }
  }
  return out
}

/**
 * Encode a navy ref payload for use inside a markdown link href.
 * encodeURIComponent alone is not enough: it leaves `()!'*` unescaped and a
 * raw `)` (or space) inside `[text](#href)` terminates the link early.
 */
export function encodeRefPayload(payload: string): string {
  return encodeURIComponent(payload).replace(
    /[()!'*]/g,
    (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase()
  )
}

export function decodeRefPayload(encoded: string): string {
  try {
    return decodeURIComponent(encoded)
  } catch {
    return encoded
  }
}

/** Split an optional trailing `:p{N}` page anchor off a navy ref payload. */
export function splitNavyPayload(payload: string): { docId: string; page?: number } {
  const m = payload.match(/:p(\d+)$/)
  if (m) {
    return { docId: payload.slice(0, m.index), page: parseInt(m[1], 10) }
  }
  return { docId: payload }
}

export interface ParsedReference {
  type: ReferenceType
  id: string
  originalText: string
  startIndex: number
  endIndex: number
}

// ExtractedReference and ExtractedReferences are kept for backward compatibility
// but not currently used in the codebase
export interface ExtractedReference {
  type: ReferenceType
  id: string
  originalText: string
  placeholder: string
}

export interface ExtractedReferences {
  processedText: string
  references: ExtractedReference[]
}

export interface ReferenceData {
  number: number
  type: ReferenceType
  id: string
}

/**
 * Parse source references from text
 *
 * Handles various formats:
 * - [source:abc123] → single reference
 * - [note:a], [note:b] → multiple references
 * - [note:a, note:b] → comma-separated references (edge case from LLM)
 * - Mixed: [source:x, note:y, source_insight:z]
 *
 * @param text - Text containing references
 * @returns Array of parsed references
 */
export function parseSourceReferences(text: string): ParsedReference[] {
  // Match pattern: (source_insight|insight|note|source):alphanumeric_id
  // This handles references both inside and outside brackets. `insight` is
  // an alias the prompts emit for source_insight.
  const pattern = /(source_insight|insight|note|source):([a-zA-Z0-9_]+)/g
  const matches: ParsedReference[] = []

  let match
  while ((match = pattern.exec(text)) !== null) {
    const type = (match[1] === 'insight' ? 'source_insight' : match[1]) as ReferenceType
    const id = match[2]

    matches.push({
      type,
      id,
      originalText: match[0],
      startIndex: match.index,
      endIndex: pattern.lastIndex
    })
  }

  // Navy refs are matched bracket-bounded (raw-filename ids); indices cover
  // the inner `navy:{payload}` span so callers' bracket-context handling
  // (looking one char around the match) works unchanged.
  for (const navy of findNavyRefs(text)) {
    matches.push({
      type: 'navy',
      id: navy.payload,
      originalText: `navy:${navy.payload}`,
      startIndex: navy.start,
      endIndex: navy.end
    })
  }

  matches.sort((a, b) => a.startIndex - b.startIndex)
  return matches
}

/**
 * Convert source references in text to clickable React elements
 *
 * @param text - Text containing references
 * @param onReferenceClick - Callback when reference is clicked (type, id)
 * @returns React nodes with clickable reference buttons
 */
export function convertSourceReferences(
  text: string,
  onReferenceClick: (type: ReferenceType, id: string) => void
): React.ReactNode {
  const matches = parseSourceReferences(text)

  if (matches.length === 0) return text

  const parts: React.ReactNode[] = []
  let lastIndex = 0

  matches.forEach((match, idx) => {
    // Check if there are brackets before the match
    const beforeMatch = text.substring(Math.max(0, match.startIndex - 2), match.startIndex)
    const hasDoubleBracketBefore = beforeMatch === '[['
    const hasSingleBracketBefore = beforeMatch.endsWith('[') && !hasDoubleBracketBefore

    // Determine where to start including text
    let textStartIndex = lastIndex
    if (hasDoubleBracketBefore && lastIndex === match.startIndex - 2) {
      textStartIndex = match.startIndex - 2
    } else if (hasSingleBracketBefore && lastIndex === match.startIndex - 1) {
      textStartIndex = match.startIndex - 1
    }

    // Add text before match (excluding brackets we'll include in the button)
    if (textStartIndex < match.startIndex && lastIndex < textStartIndex) {
      parts.push(text.substring(lastIndex, textStartIndex))
    } else if (lastIndex < match.startIndex && !hasSingleBracketBefore && !hasDoubleBracketBefore) {
      parts.push(text.substring(lastIndex, match.startIndex))
    }

    // Check if there are brackets after the match
    const afterMatch = text.substring(match.endIndex, Math.min(text.length, match.endIndex + 2))
    const hasDoubleBracketAfter = afterMatch === ']]'
    const hasSingleBracketAfter = afterMatch.startsWith(']') && !hasDoubleBracketAfter

    // Determine the display text with appropriate brackets
    let displayText = match.originalText
    if (hasDoubleBracketBefore && hasDoubleBracketAfter) {
      displayText = `[[${match.originalText}]]`
    } else if (hasSingleBracketBefore && hasSingleBracketAfter) {
      displayText = `[${match.originalText}]`
    } else {
      displayText = match.originalText
    }

    // Add clickable reference button
    parts.push(
      <button
        key={`ref-${idx}-${match.type}-${match.id}`}
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          onReferenceClick(match.type, match.id)
        }}
        className="text-primary hover:underline cursor-pointer inline font-medium"
        type="button"
      >
        {displayText}
      </button>
    )

    // Update lastIndex to skip the closing brackets
    if (hasDoubleBracketAfter) {
      lastIndex = match.endIndex + 2
    } else if (hasSingleBracketAfter) {
      lastIndex = match.endIndex + 1
    } else {
      lastIndex = match.endIndex
    }
  })

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex))
  }

  return <>{parts}</>
}

/**
 * Convert references in text to markdown links
 * Use this BEFORE passing text to ReactMarkdown
 *
 * Handles complex patterns including:
 * - Plain references: source:abc → [source:abc](#ref-source-abc)
 * - Bracketed: [source:abc] → [[source:abc]](#ref-source-abc)
 * - Double brackets: [[source:abc]] → [[[source:abc]]](#ref-source-abc)
 * - With bold: [**source:abc**] → [**source:abc**](#ref-source-abc)
 * - After commas: [source:a, note:b] → each converted separately
 * - Nested: [**source:a**, [source_insight:b]] → both converted
 *
 * Uses greedy matching to catch all references regardless of surrounding context.
 *
 * @param text - Original text with references
 * @returns Text with references converted to markdown links
 */
export function convertReferencesToMarkdownLinks(text: string): string {
  // Step 0: Navy refs first — bracket-bounded, raw-filename payloads that the
  // generic charset pattern cannot express. `[navy:X]` → `[[navy:X]](#href)`
  // matching the single-bracket display convention below; a navy ref sharing
  // its bracket with other refs is linked in place without consuming the
  // bracket. The payload is percent-encoded because spaces/parens would
  // terminate the markdown href.
  const navyRefs = findNavyRefs(text)
  for (let i = navyRefs.length - 1; i >= 0; i--) {
    const navy = navyRefs[i]
    const href = `#ref-navy-${encodeRefPayload(navy.payload)}`
    if (navy.wholeBracket) {
      text =
        text.slice(0, navy.start - 1) +
        `[[navy:${navy.payload}]](${href})` +
        text.slice(navy.end + 1)
    } else {
      text =
        text.slice(0, navy.start) +
        `[navy:${navy.payload}](${href})` +
        text.slice(navy.end)
    }
  }

  // Step 1: Find ALL references using simple greedy pattern
  const refPattern = /(source_insight|insight|note|source):([a-zA-Z0-9_]+)/g
  const references: Array<{ type: string; id: string; index: number; length: number }> = []

  let match
  while ((match = refPattern.exec(text)) !== null) {
    const type = match[1] === 'insight' ? 'source_insight' : match[1]
    const id = match[2]

    // Validate the reference
    const validTypes = ['source', 'source_insight', 'note']
    if (!validTypes.includes(type) || !id || id.length === 0 || id.length > 100) {
      continue // Skip invalid references
    }

    references.push({
      type,
      id,
      index: match.index,
      length: match[0].length
    })
  }

  // If no references found, return original text
  if (references.length === 0) return text

  // Step 2: Process references from end to start (to preserve indices)
  let result = text
  for (let i = references.length - 1; i >= 0; i--) {
    const ref = references[i]
    const refStart = ref.index
    const refEnd = refStart + ref.length
    const refText = `${ref.type}:${ref.id}`

    // Step 3: Analyze context around the reference
    // Look back up to 50 chars for opening brackets/bold markers
    const contextBefore = result.substring(Math.max(0, refStart - 50), refStart)
    // Look ahead up to 50 chars for closing brackets/bold markers
    const contextAfter = result.substring(refEnd, Math.min(result.length, refEnd + 50))

    // Determine display text by checking immediate surroundings
    let displayText = refText
    let replaceStart = refStart
    let replaceEnd = refEnd

    // Check for double brackets [[ref]]
    if (contextBefore.endsWith('[[') && contextAfter.startsWith(']]')) {
      displayText = `[[${refText}]]`
      replaceStart = refStart - 2
      replaceEnd = refEnd + 2
    }
    // Check for single brackets [ref]
    else if (contextBefore.endsWith('[') && contextAfter.startsWith(']')) {
      displayText = `[${refText}]`
      replaceStart = refStart - 1
      replaceEnd = refEnd + 1
    }
    // Check for bold with brackets [**ref**]
    else if (contextBefore.endsWith('[**') && contextAfter.startsWith('**]')) {
      displayText = `[**${refText}**]`
      replaceStart = refStart - 3
      replaceEnd = refEnd + 3
    }
    // Check for just bold **ref**
    else if (contextBefore.endsWith('**') && contextAfter.startsWith('**')) {
      displayText = `**${refText}**`
      replaceStart = refStart - 2
      replaceEnd = refEnd + 2
    }
    // Plain reference (no brackets)
    else {
      displayText = refText
    }

    // Step 4: Build the markdown link
    const href = `#ref-${ref.type}-${ref.id}`
    const markdownLink = `[${displayText}](${href})`

    // Step 5: Replace in the result string
    result = result.substring(0, replaceStart) + markdownLink + result.substring(replaceEnd)
  }

  return result
}

/**
 * Create a custom link component for ReactMarkdown that handles reference links
 *
 * @param onReferenceClick - Callback for when a reference link is clicked
 * @returns React component for rendering links
 */
export function createReferenceLinkComponent(
  onReferenceClick: (type: ReferenceType, id: string) => void
) {
  const ReferenceLinkComponent = ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href?: string
    children?: React.ReactNode
  }) => {
    // Check if this is a reference link (starts with #ref-)
    if (href?.startsWith('#ref-')) {
      // Parse: #ref-source-abc123 → type=source, id=abc123
      const parts = href.substring(5).split('-') // Remove '#ref-'
      const type = parts[0] as ReferenceType
      const rawId = parts.slice(1).join('-') // Rejoin in case ID has dashes
      // Navy payloads are percent-encoded raw filenames
      const id = type === 'navy' ? decodeRefPayload(rawId) : rawId

      // Select appropriate icon based on reference type
      const IconComponent =
        type === 'source' ? FileText :
        type === 'source_insight' ? Lightbulb :
        type === 'navy' ? Anchor :
        FileEdit // note

      return (
        <button
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onReferenceClick(type, id)
          }}
          className="text-primary hover:underline cursor-pointer inline font-medium"
          type="button"
        >
          <IconComponent className="h-3 w-3 inline mr-1" aria-hidden="true" />
          {children}
        </button>
      )
    }

    // Regular link - open in new tab
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" {...props} className="text-primary hover:underline">
        {children}
      </a>
    )
  }

  ReferenceLinkComponent.displayName = 'ReferenceLinkComponent'
  return ReferenceLinkComponent
}

/**
 * Convert references in text to compact numbered format with reference list
 *
 * This function transforms verbose inline references like [source:abc123] into
 * compact numbered citations [1], [2], etc., and appends a "References:" section
 * at the bottom of the message with the full reference details.
 *
 * Algorithm:
 * 1. Parse all references using parseSourceReferences()
 * 2. Build a reference map to deduplicate and assign numbers
 * 3. Replace inline references with numbered citations
 * 4. Append reference list at the bottom
 *
 * @param text - Original text with references
 * @param referencesLabel - Locales label for "References" title (default: "References")
 * @returns Text with numbered citations and reference list appended
 *
 * @example
 * Input: "See [source:abc] and [note:xyz]. Also [source:abc] again."
 * Output: "See [1] and [2]. Also [1] again.\n\nReferences:\n[1] - [source:abc]\n[2] - [note:xyz]"
 */
export function convertReferencesToCompactMarkdown(text: string, referencesLabel: string = 'References'): string {
  // Step 1: Parse all references using existing function
  const references = parseSourceReferences(text)

  // Step 2: If no references found, return original text
  if (references.length === 0) {
    return text
  }

  // Step 3: Build reference map (deduplicate and assign numbers)
  const referenceMap = new Map<string, ReferenceData>()
  let nextNumber = 1

  for (const reference of references) {
    const key = `${reference.type}:${reference.id}`
    if (!referenceMap.has(key)) {
      referenceMap.set(key, {
        number: nextNumber++,
        type: reference.type,
        id: reference.id
      })
    }
  }

  // Step 4: Replace references with numbered citations (process from end to start)
  let result = text
  for (let i = references.length - 1; i >= 0; i--) {
    const reference = references[i]
    const key = `${reference.type}:${reference.id}`
    const refData = referenceMap.get(key)!
    const number = refData.number

    // Analyze context around the reference
    const refStart = reference.startIndex
    const refEnd = reference.endIndex
    const contextBefore = result.substring(Math.max(0, refStart - 2), refStart)
    const contextAfter = result.substring(refEnd, Math.min(result.length, refEnd + 2))

    // Determine what to replace based on bracket context
    let replaceStart = refStart
    let replaceEnd = refEnd

    // Check for double brackets [[ref]]
    if (contextBefore === '[[' && contextAfter.startsWith(']]')) {
      replaceStart = refStart - 2
      replaceEnd = refEnd + 2
    }
    // Check for single brackets [ref]
    else if (contextBefore.endsWith('[') && contextAfter.startsWith(']')) {
      replaceStart = refStart - 1
      replaceEnd = refEnd + 1
    }

    // Build the numbered citation with full reference in href. Navy ids are
    // raw filenames — percent-encode them or the markdown href breaks.
    const hrefId =
      reference.type === 'navy' ? encodeRefPayload(reference.id) : reference.id
    const citationLink = `[${number}](#ref-${reference.type}-${hrefId})`

    // Replace in the result string
    result = result.substring(0, replaceStart) + citationLink + result.substring(replaceEnd)
  }

  // Step 5: Build reference list with human-readable type labels
  const typeLabels: Record<string, string> = {
    source: '📄 Source',
    source_insight: '💡 Insight',
    note: '📝 Note',
    navy: '⚓ Document',
  }
  const refListLines: string[] = [`\n\n---\n\n**${referencesLabel}:**`]

  // Iterate through reference map in insertion order (Map preserves order)
  for (const [, refData] of referenceMap) {
    const label = typeLabels[refData.type] || refData.type
    const listHrefId =
      refData.type === 'navy' ? encodeRefPayload(refData.id) : refData.id
    const refListItem = `**[${refData.number}]** ${label} — [${refData.type}:${refData.id}](#ref-${refData.type}-${listHrefId})`
    refListLines.push(refListItem)
  }

  // Step 6: Append reference list to result
  result = result + refListLines.join('\n\n')

  return result
}

/**
 * Create a custom link component for ReactMarkdown that handles compact reference links
 *
 * This component handles two types of reference links:
 * 1. Numbered citations in text: [1](#ref-source-abc123)
 * 2. Reference list items: [source:abc123](#ref-source-abc123)
 *
 * Both use the same href format: #ref-{type}-{id}
 * The component extracts the type and id from the href and triggers the click handler.
 *
 * @param onReferenceClick - Callback for when a reference link is clicked
 * @returns React component for rendering links in ReactMarkdown
 *
 * @example
 * const LinkComponent = createCompactReferenceLinkComponent((type, id) => openModal(type, id))
 * <ReactMarkdown components={{ a: LinkComponent }}>...</ReactMarkdown>
 */
export function createCompactReferenceLinkComponent(
  onReferenceClick: (type: ReferenceType, id: string) => void
) {
  const CompactReferenceLinkComponent = ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href?: string
    children?: React.ReactNode
  }) => {
    // Check if this is a reference link (starts with #ref-)
    if (href?.startsWith('#ref-')) {
      // Parse: #ref-source-abc123 → type=source, id=abc123
      const parts = href.substring(5).split('-') // Remove '#ref-'
      const type = parts[0] as ReferenceType
      const rawId = parts.slice(1).join('-') // Rejoin in case ID has dashes
      // Navy payloads are percent-encoded raw filenames
      const id = type === 'navy' ? decodeRefPayload(rawId) : rawId

      // Select icon based on reference type
      const IconComponent =
        type === 'source' ? FileText :
        type === 'source_insight' ? Lightbulb :
        type === 'navy' ? Anchor :
        FileEdit // note

      return (
        <button
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onReferenceClick(type, id)
          }}
          className="inline-flex items-center gap-0.5 text-primary hover:underline cursor-pointer font-medium"
          type="button"
        >
          <IconComponent className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
          {children}
        </button>
      )
    }

    // Regular link - open in new tab
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" {...props} className="text-primary hover:underline">
        {children}
      </a>
    )
  }

  CompactReferenceLinkComponent.displayName = 'CompactReferenceLinkComponent'
  return CompactReferenceLinkComponent
}

/**
 * Legacy function for backward compatibility
 * Converts old Link-based references to new click handler approach
 *
 * @deprecated Use extractReferences + replacePlaceholdersWithButtons instead
 */
export function convertSourceReferencesLegacy(text: string): React.ReactNode {
  // For legacy support, just return text as-is
  // Components should migrate to new convertSourceReferences function
  return text
}
