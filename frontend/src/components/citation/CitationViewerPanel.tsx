'use client'

import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { isAxiosError } from 'axios'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { HighlightedDocumentViewer } from '@/components/citation/HighlightedDocumentViewer'
import { useCitationViewerStore, useCitedDocument, useDeleteCitation } from '@/lib/hooks/use-citation-viewer'
import { useSource } from '@/lib/hooks/use-sources'
import { useTranslation } from '@/lib/hooks/use-translation'
import { CitationTarget, CitedDocumentResponse, CitationHighlight } from '@/lib/types/citations'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function collapseWhitespace(s: string): string {
  return s.replace(/\s+/g, ' ').trim()
}

/**
 * Attempts to locate `snippet` inside `fullText`.
 * 1. Exact indexOf
 * 2. Collapse whitespace runs on both, then map the collapsed match position
 *    back to the original string by scanning character by character.
 */
function locateSnippet(
  fullText: string,
  snippet: string
): CitationHighlight | null {
  // Exact match
  const exact = fullText.indexOf(snippet)
  if (exact !== -1) {
    return { start: exact, end: exact + snippet.length }
  }

  // Collapsed match
  const collapsedFull = collapseWhitespace(fullText)
  const collapsedSnippet = collapseWhitespace(snippet)
  const collapsedIdx = collapsedFull.indexOf(collapsedSnippet)
  if (collapsedIdx === -1) return null

  // Map collapsed index back to original
  let origIdx = 0
  let collIdx = 0

  while (origIdx < fullText.length && collIdx < collapsedIdx) {
    const ch = fullText[origIdx]
    if (/\s/.test(ch)) {
      // Skip all whitespace in original, advance collapsed cursor by 1 (the space)
      while (origIdx < fullText.length && /\s/.test(fullText[origIdx])) {
        origIdx++
      }
      collIdx++
    } else {
      origIdx++
      collIdx++
    }
  }

  const start = origIdx

  // Now advance origIdx by the length of the snippet (in collapsed chars)
  const collEndIdx = collapsedIdx + collapsedSnippet.length
  collIdx = collapsedIdx

  while (origIdx < fullText.length && collIdx < collEndIdx) {
    const ch = fullText[origIdx]
    if (/\s/.test(ch)) {
      while (origIdx < fullText.length && /\s/.test(fullText[origIdx])) {
        origIdx++
      }
      collIdx++
    } else {
      origIdx++
      collIdx++
    }
  }

  return { start, end: origIdx }
}

// ---------------------------------------------------------------------------
// Governance badges
// ---------------------------------------------------------------------------

interface GovernanceBadgesProps {
  doc: CitedDocumentResponse
}

function GovernanceBadges({ doc }: GovernanceBadgesProps) {
  return (
    <div className="flex flex-wrap gap-1.5 px-4 pb-2 pt-1">
      {doc.document_type && (
        <Badge variant="secondary" className="text-xs">
          {doc.document_type}
        </Badge>
      )}
      {doc.classification_level != null && doc.classification_level > 0 && (
        <Badge variant="outline" className="text-xs">
          L{doc.classification_level}
        </Badge>
      )}
      {doc.creator_department && (
        <Badge variant="outline" className="text-xs">
          {doc.creator_department}
        </Badge>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inner panels
// ---------------------------------------------------------------------------

interface NavyPanelContentProps {
  ref_: string
  chunkId?: string
  snippet?: string
  onTitle: (title: string) => void
}

function NavyPanelContent({ ref_, chunkId, snippet, onTitle }: NavyPanelContentProps) {
  const { t } = useTranslation()
  const deleteMutation = useDeleteCitation()
  const materializedIdRef = useRef<string | null>(null)
  const { data: doc, isLoading, isError, error } = useCitedDocument(ref_, chunkId, snippet)

  useEffect(() => {
    if (doc) {
      materializedIdRef.current = doc.id
      onTitle(doc.title)
    }
  }, [doc, onTitle])

  useEffect(() => {
    return () => {
      // On unmount (panel closed / target switched): fire-and-forget delete
      // of the temporary record. The cached response keeps reopens instant.
      if (materializedIdRef.current) {
        deleteMutation.mutate(materializedIdRef.current)
        materializedIdRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <LoadingSpinner />
        <span className="ml-2 text-sm text-muted-foreground">{t.citationViewer.loading}</span>
      </div>
    )
  }

  if (isError) {
    const status = isAxiosError(error) ? error.response?.status : undefined
    const message =
      status === 404 || status === 400
        ? t.citationViewer.accessDenied
        : t.citationViewer.loadError

    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <p className="text-sm text-destructive">{message}</p>
      </div>
    )
  }

  if (!doc) return null

  const highlights: CitationHighlight[] =
    doc.highlights && doc.highlights.length > 0
      ? doc.highlights
      : snippet
        ? (() => {
            const found = locateSnippet(doc.full_text, snippet)
            return found ? [found] : []
          })()
        : []

  return (
    <>
      <GovernanceBadges doc={doc} />
      <div className="flex-1 overflow-y-auto p-4">
        <HighlightedDocumentViewer
          fullText={doc.full_text}
          highlights={highlights}
          markdown={false}
        />
      </div>
    </>
  )
}

interface SourcePanelContentProps {
  sourceId: string
  snippet?: string
  onTitle: (title: string) => void
}

function SourcePanelContent({ sourceId, snippet, onTitle }: SourcePanelContentProps) {
  const { t } = useTranslation()
  const { data: source, isLoading, isError, error } = useSource(sourceId)

  useEffect(() => {
    if (source?.title) {
      onTitle(source.title)
    }
  }, [source?.title, onTitle])

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <LoadingSpinner />
        <span className="ml-2 text-sm text-muted-foreground">{t.citationViewer.loading}</span>
      </div>
    )
  }

  if (isError) {
    const status = isAxiosError(error) ? error.response?.status : undefined
    const message =
      status === 404 || status === 403
        ? t.citationViewer.accessDenied
        : t.citationViewer.loadError

    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <p className="text-sm text-destructive">{message}</p>
      </div>
    )
  }

  if (!source) return null

  const fullText = source.full_text || ''

  let highlights: CitationHighlight[] = []
  let snippetNotFound = false

  if (snippet) {
    const found = locateSnippet(fullText, snippet)
    if (found) {
      highlights = [found]
    } else {
      snippetNotFound = true
    }
  }

  const useMarkdown = !snippet || snippetNotFound

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {snippetNotFound && (
        <div className="px-4 pt-2">
          <p className="text-xs text-muted-foreground">{t.citationViewer.notFoundInDocument}</p>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-4">
        <HighlightedDocumentViewer
          fullText={fullText}
          highlights={highlights}
          markdown={useMarkdown}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel component
// ---------------------------------------------------------------------------

export default function CitationViewerPanel() {
  const { t } = useTranslation()
  const { isOpen, target, closeCitation } = useCitationViewerStore()

  const [panelTitle, setPanelTitle] = useState<string>('')

  // The store keeps `target` after close (so the slide-out animation doesn't
  // flash empty), but the inner content must UNMOUNT once the panel is closed
  // — its unmount cleanup is what deletes the materialized cited_document.
  // Render from a delayed copy that clears shortly after the animation ends.
  const [renderTarget, setRenderTarget] = useState<CitationTarget | null>(null)
  useEffect(() => {
    if (isOpen && target) {
      setRenderTarget(target)
      return
    }
    const timer = setTimeout(() => setRenderTarget(null), 350)
    return () => clearTimeout(timer)
  }, [isOpen, target])

  // Reset title when target changes
  useEffect(() => {
    if (renderTarget?.kind === 'navy') {
      setPanelTitle(renderTarget.ref)
    } else if (renderTarget?.kind === 'source') {
      setPanelTitle(renderTarget.id)
    }
  }, [renderTarget])

  // Stable key so inner panels remount when target changes
  const targetKey =
    renderTarget?.kind === 'navy'
      ? `navy:${renderTarget.ref}:${renderTarget.chunkId ?? ''}`
      : renderTarget?.kind === 'source'
        ? `source:${renderTarget.id}`
        : 'empty'

  return (
    <div
      className={cn(
        'fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l bg-background shadow-xl transition-transform duration-300',
        'sm:w-[42vw] sm:min-w-[420px] sm:max-w-2xl',
        isOpen ? 'translate-x-0' : 'translate-x-full'
      )}
      aria-label={t.citationViewer.documentViewer}
      aria-hidden={!isOpen}
      role="complementary"
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b px-4 py-3">
        <h2 className="line-clamp-1 text-sm font-semibold">
          {panelTitle || t.citationViewer.documentViewer}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={closeCitation}
          aria-label={t.citationViewer.close}
          className="shrink-0"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Body */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {renderTarget?.kind === 'navy' && (
          <NavyPanelContent
            key={targetKey}
            ref_={renderTarget.ref}
            chunkId={renderTarget.chunkId}
            snippet={renderTarget.snippet}
            onTitle={setPanelTitle}
          />
        )}
        {renderTarget?.kind === 'source' && (
          <SourcePanelContent
            key={targetKey}
            sourceId={renderTarget.id}
            snippet={renderTarget.snippet}
            onTitle={setPanelTitle}
          />
        )}
        {!renderTarget && (
          <div className="flex flex-1 items-center justify-center">
            <LoadingSpinner />
          </div>
        )}
      </div>
    </div>
  )
}
