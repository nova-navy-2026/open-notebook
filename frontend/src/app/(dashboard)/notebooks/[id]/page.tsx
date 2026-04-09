'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { NotebookHeader } from '../components/NotebookHeader'
import { SourcesColumn } from '../components/SourcesColumn'
import { NotesColumn } from '../components/NotesColumn'
import { ChatColumn } from '../components/ChatColumn'
import { useNotebook } from '@/lib/hooks/use-notebooks'
import { useNotebookSources } from '@/lib/hooks/use-sources'
import { useNotes } from '@/lib/hooks/use-notes'
import { useNavyDocuments } from '@/lib/hooks/use-navy-docs'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useNotebookColumnsStore } from '@/lib/stores/notebook-columns-store'
import { useIsDesktop } from '@/lib/hooks/use-media-query'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FileText, StickyNote, MessageSquare } from 'lucide-react'

export type ContextMode = 'off' | 'insights' | 'full'

export interface ContextSelections {
  sources: Record<string, ContextMode>
  notes: Record<string, ContextMode>
}

export default function NotebookPage() {
  const { t } = useTranslation()
  const params = useParams()

  // Ensure the notebook ID is properly decoded from URL
  const notebookId = params?.id ? decodeURIComponent(params.id as string) : ''

  const { data: notebook, isLoading: notebookLoading } = useNotebook(notebookId)
  const {
    sources,
    isLoading: sourcesLoading,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId)
  const { data: notes, isLoading: notesLoading } = useNotes(notebookId)

  // Get collapse states for dynamic layout
  const { sourcesCollapsed, notesCollapsed } = useNotebookColumnsStore()

  // Detect desktop to avoid double-mounting ChatColumn
  const isDesktop = useIsDesktop()

  // Mobile tab state (Sources, Notes, or Chat)
  const [mobileActiveTab, setMobileActiveTab] = useState<'sources' | 'notes' | 'chat'>('chat')

  // Context selection state
  const [contextSelections, setContextSelections] = useState<ContextSelections>({
    sources: {},
    notes: {}
  })

  // Initialize and update selections when sources load or change
  useEffect(() => {
    if (sources && sources.length > 0) {
      setContextSelections(prev => {
        const newSourceSelections = { ...prev.sources }
        sources.forEach(source => {
          const currentMode = newSourceSelections[source.id]
          const hasInsights = source.insights_count > 0

          if (currentMode === undefined) {
            // Initial setup - default based on insights availability
            newSourceSelections[source.id] = hasInsights ? 'insights' : 'full'
          } else if (currentMode === 'full' && hasInsights) {
            // Source gained insights while in 'full' mode - auto-switch to 'insights'
            newSourceSelections[source.id] = 'insights'
          }
        })
        return { ...prev, sources: newSourceSelections }
      })
    }
  }, [sources])

  useEffect(() => {
    if (notes && notes.length > 0) {
      setContextSelections(prev => {
        const newNoteSelections = { ...prev.notes }
        notes.forEach(note => {
          // Only set default if not already set
          if (!(note.id in newNoteSelections)) {
            // Notes default to 'full'
            newNoteSelections[note.id] = 'full'
          }
        })
        return { ...prev, notes: newNoteSelections }
      })
    }
  }, [notes])

  // Navy corpus document selection state
  const { data: navyData } = useNavyDocuments()
  const [selectedNavyDocIds, setSelectedNavyDocIds] = useState<Set<string>>(new Set())
  const [navyDocsInitialized, setNavyDocsInitialized] = useState(false)

  // Initialize: select all navy docs by default
  useEffect(() => {
    if (navyData?.documents && navyData.documents.length > 0 && !navyDocsInitialized) {
      setSelectedNavyDocIds(new Set(navyData.documents.map(d => d.doc_id)))
      setNavyDocsInitialized(true)
    }
  }, [navyData, navyDocsInitialized])

  const handleNavyDocSelectionChange = useCallback((docId: string, selected: boolean) => {
    setSelectedNavyDocIds(prev => {
      const next = new Set(prev)
      if (selected) next.add(docId)
      else next.delete(docId)
      return next
    })
  }, [])

  const handleNavySelectAll = useCallback((selected: boolean) => {
    if (selected && navyData?.documents) {
      setSelectedNavyDocIds(new Set(navyData.documents.map(d => d.doc_id)))
    } else {
      setSelectedNavyDocIds(new Set())
    }
  }, [navyData])

  // Handler to update context selection
  const handleContextModeChange = (itemId: string, mode: ContextMode, type: 'source' | 'note') => {
    setContextSelections(prev => ({
      ...prev,
      [type === 'source' ? 'sources' : 'notes']: {
        ...(type === 'source' ? prev.sources : prev.notes),
        [itemId]: mode
      }
    }))
  }

  if (notebookLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!notebook) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">{t.notebooks.notFound}</h1>
        <p className="text-muted-foreground">{t.notebooks.notFoundDesc}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
        <div className="flex-shrink-0 p-6 pb-0">
          <NotebookHeader notebook={notebook} />
        </div>

        <div className="flex-1 p-6 pt-6 overflow-hidden flex flex-col">
          {/* Mobile: Tabbed interface - only render on mobile to avoid double-mounting */}
          {!isDesktop && (
            <>
              <div className="lg:hidden mb-4">
                <Tabs value={mobileActiveTab} onValueChange={(value) => setMobileActiveTab(value as 'sources' | 'notes' | 'chat')}>
                  <TabsList className="grid w-full grid-cols-3">
                    <TabsTrigger value="sources" className="gap-2">
                      <FileText className="h-4 w-4" />
                      {t.navigation.sources}
                    </TabsTrigger>
                    <TabsTrigger value="notes" className="gap-2">
                      <StickyNote className="h-4 w-4" />
                      {t.common.notes}
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
                {mobileActiveTab === 'sources' && (
                  <SourcesColumn
                    sources={sources}
                    isLoading={sourcesLoading}
                    notebookId={notebookId}
                    notebookName={notebook?.name}
                    onRefresh={refetchSources}
                    contextSelections={contextSelections.sources}
                    onContextModeChange={(sourceId, mode) => handleContextModeChange(sourceId, mode, 'source')}
                    hasNextPage={hasNextPage}
                    isFetchingNextPage={isFetchingNextPage}
                    fetchNextPage={fetchNextPage}
                    selectedNavyDocIds={selectedNavyDocIds}
                    onNavyDocSelectionChange={handleNavyDocSelectionChange}
                    onNavyDocSelectAll={handleNavySelectAll}
                  />
                )}
                {mobileActiveTab === 'notes' && (
                  <NotesColumn
                    notes={notes}
                    isLoading={notesLoading}
                    notebookId={notebookId}
                    contextSelections={contextSelections.notes}
                    onContextModeChange={(noteId, mode) => handleContextModeChange(noteId, mode, 'note')}
                  />
                )}
                {mobileActiveTab === 'chat' && (
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

          {/* Desktop: Collapsible columns layout */}
          <div className={cn(
            'hidden lg:grid h-full min-h-0 gap-4 transition-all duration-150',
            sourcesCollapsed && notesCollapsed
              ? 'grid-cols-[auto_auto_1fr]'
              : sourcesCollapsed
                ? 'grid-cols-[auto_1fr_1fr]'
                : notesCollapsed
                  ? 'grid-cols-[1fr_auto_1fr]'
                  : 'grid-cols-3'
          )}>
            {/* Sources Column */}
            <div className={cn(
              'transition-all duration-150 min-w-0 overflow-hidden',
              sourcesCollapsed && 'w-12'
            )}>
              <SourcesColumn
                sources={sources}
                isLoading={sourcesLoading}
                notebookId={notebookId}
                notebookName={notebook?.name}
                onRefresh={refetchSources}
                contextSelections={contextSelections.sources}
                onContextModeChange={(sourceId, mode) => handleContextModeChange(sourceId, mode, 'source')}
                hasNextPage={hasNextPage}
                isFetchingNextPage={isFetchingNextPage}
                fetchNextPage={fetchNextPage}
                selectedNavyDocIds={selectedNavyDocIds}
                onNavyDocSelectionChange={handleNavyDocSelectionChange}
                onNavyDocSelectAll={handleNavySelectAll}
              />
            </div>

            {/* Notes Column */}
            <div className={cn(
              'transition-all duration-150 min-w-0 overflow-hidden',
              notesCollapsed && 'w-12'
            )}>
              <NotesColumn
                notes={notes}
                isLoading={notesLoading}
                notebookId={notebookId}
                contextSelections={contextSelections.notes}
                onContextModeChange={(noteId, mode) => handleContextModeChange(noteId, mode, 'note')}
              />
            </div>

            {/* Chat Column - always expanded, takes remaining space */}
            <div className="transition-all duration-150 min-w-0 overflow-hidden">
              <ChatColumn
                notebookId={notebookId}
                contextSelections={contextSelections}
                sources={sources}
                sourcesLoading={sourcesLoading}
                selectedNavyDocIds={selectedNavyDocIds}
              />
            </div>
          </div>
        </div>
    </div>
  )
}
