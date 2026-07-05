'use client'

import { useEffect, useMemo, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CitationHighlight } from '@/lib/types/citations'

interface HighlightedDocumentViewerProps {
  fullText: string
  highlights: CitationHighlight[]
  markdown?: boolean
}

interface TextSegment {
  text: string
  highlighted: boolean
}

function mergeHighlights(highlights: CitationHighlight[], textLength: number): CitationHighlight[] {
  if (highlights.length === 0) return []

  // Clamp and sort
  const clamped = highlights
    .map((h) => ({
      start: Math.max(0, h.start),
      end: Math.min(textLength, h.end),
    }))
    .filter((h) => h.start < h.end)
    .sort((a, b) => a.start - b.start)

  if (clamped.length === 0) return []

  // Merge overlapping
  const merged: CitationHighlight[] = [clamped[0]]
  for (let i = 1; i < clamped.length; i++) {
    const last = merged[merged.length - 1]
    if (clamped[i].start <= last.end) {
      last.end = Math.max(last.end, clamped[i].end)
    } else {
      merged.push({ ...clamped[i] })
    }
  }
  return merged
}

function buildSegments(fullText: string, highlights: CitationHighlight[]): TextSegment[] {
  const merged = mergeHighlights(highlights, fullText.length)
  if (merged.length === 0) {
    return [{ text: fullText, highlighted: false }]
  }

  const segments: TextSegment[] = []
  let cursor = 0

  for (const hl of merged) {
    if (cursor < hl.start) {
      segments.push({ text: fullText.slice(cursor, hl.start), highlighted: false })
    }
    segments.push({ text: fullText.slice(hl.start, hl.end), highlighted: true })
    cursor = hl.end
  }

  if (cursor < fullText.length) {
    segments.push({ text: fullText.slice(cursor), highlighted: false })
  }

  return segments
}

export function HighlightedDocumentViewer({
  fullText,
  highlights,
  markdown = false,
}: HighlightedDocumentViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  // Documents run to hundreds of kB — don't re-slice them on unrelated
  // re-renders (e.g. the panel title updating).
  const segments = useMemo(
    () => (markdown ? [] : buildSegments(fullText, highlights)),
    [fullText, highlights, markdown]
  )

  useEffect(() => {
    // Jump to the first highlight as soon as it exists in the DOM. The panel
    // slides in with a CSS transform, and smooth-scrolling a 300k-char
    // document during that transition is unreliable — so retry a few times
    // and jump instantly (block: center).
    let done = false
    const timers: number[] = []

    const tryScroll = () => {
      if (done) return
      const el = containerRef.current?.querySelector<HTMLElement>(
        '[data-citation-mark="first"]'
      )
      if (!el) return
      done = true
      el.scrollIntoView({ behavior: 'auto', block: 'center' })
      el.classList.add('ring-2', 'ring-amber-400')
      timers.push(
        window.setTimeout(() => {
          el.classList.remove('ring-2', 'ring-amber-400')
        }, 1600)
      )
    }

    const raf = requestAnimationFrame(tryScroll)
    // Retries cover the panel's 300ms slide-in and slow first paints.
    for (const delay of [100, 350, 700]) {
      timers.push(window.setTimeout(tryScroll, delay))
    }

    return () => {
      done = true
      cancelAnimationFrame(raf)
      timers.forEach(clearTimeout)
    }
  }, [fullText, highlights])

  if (markdown) {
    return (
      <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none prose-headings:font-semibold prose-a:text-blue-600 prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-p:mb-4 prose-p:leading-7 prose-li:mb-2">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }) => <p className="mb-4">{children}</p>,
            h1: ({ children }) => <h1 className="text-2xl font-bold mt-6 mb-4">{children}</h1>,
            h2: ({ children }) => <h2 className="text-xl font-bold mt-5 mb-3">{children}</h2>,
            h3: ({ children }) => <h3 className="text-lg font-semibold mt-4 mb-2">{children}</h3>,
            ul: ({ children }) => <ul className="mb-4 list-disc pl-6">{children}</ul>,
            ol: ({ children }) => <ol className="mb-4 list-decimal pl-6">{children}</ol>,
            li: ({ children }) => <li className="mb-1">{children}</li>,
            table: ({ children }) => (
              <div className="my-4 overflow-x-auto">
                <table className="min-w-full border-collapse border border-border">{children}</table>
              </div>
            ),
            thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
            tbody: ({ children }) => <tbody>{children}</tbody>,
            tr: ({ children }) => <tr className="border-b border-border">{children}</tr>,
            th: ({ children }) => (
              <th className="border border-border px-3 py-2 text-left font-semibold">{children}</th>
            ),
            td: ({ children }) => <td className="border border-border px-3 py-2">{children}</td>,
          }}
        >
          {fullText}
        </ReactMarkdown>
      </div>
    )
  }

  let firstMarkRendered = false

  return (
    <div
      ref={containerRef}
      className="whitespace-pre-wrap font-sans text-sm leading-relaxed"
    >
      {segments.map((seg, idx) => {
        if (!seg.highlighted) {
          return <span key={idx}>{seg.text}</span>
        }

        const isFirst = !firstMarkRendered
        if (isFirst) firstMarkRendered = true

        return (
          <mark
            key={idx}
            data-citation-mark={isFirst ? 'first' : undefined}
            className="bg-amber-200 dark:bg-amber-500/40 text-foreground rounded-sm px-0.5"
          >
            {seg.text}
          </mark>
        )
      })}
    </div>
  )
}
