'use client'

import { useMemo, useState } from 'react'
import { useMultimodalChat } from '@/lib/hooks/use-multimodal'
import { useNotes } from '@/lib/hooks/use-notes'
import { ChatPanel } from '@/components/source/ChatPanel'
import { SessionManager } from '@/components/source/SessionManager'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { AlertCircle, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { ContextSelections } from '../[id]/page'
import { useTranslation } from '@/lib/hooks/use-translation'
import { SourceListResponse } from '@/lib/types/api'

interface ChatColumnProps {
  notebookId: string
  contextSelections: ContextSelections
  sources: SourceListResponse[]
  sourcesLoading: boolean
  selectedNavyDocIds?: Set<string>
}

export function ChatColumn({ notebookId, contextSelections, sources, sourcesLoading, selectedNavyDocIds }: ChatColumnProps) {
  const { t } = useTranslation()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Fetch notes for this notebook
  const { data: notes = [], isLoading: notesLoading } = useNotes(notebookId)

  // Initialize multimodal chat hook
  const chat = useMultimodalChat({
    notebookId,
    sources,
    notes,
    contextSelections,
    selectedNavyDocIds
  })

  // Calculate context stats for indicator
  const contextStats = useMemo(() => {
    let sourcesInsights = 0
    let sourcesFull = 0
    let notesCount = 0

    // Count sources by mode
    sources.forEach(source => {
      const mode = contextSelections.sources[source.id]
      if (mode === 'insights') {
        sourcesInsights++
      } else if (mode === 'full') {
        sourcesFull++
      }
    })

    // Count notes that are included (not 'off')
    notes.forEach(note => {
      const mode = contextSelections.notes[note.id]
      if (mode === 'full') {
        notesCount++
      }
    })

    return {
      sourcesInsights,
      sourcesFull,
      notesCount,
      tokenCount: chat.tokenCount,
      charCount: chat.charCount
    }
  }, [sources, notes, contextSelections, chat.tokenCount, chat.charCount])

  // Show loading state while sources/notes are being fetched
  if (sourcesLoading || notesLoading) {
    return (
      <Card className="h-full flex flex-col">
        <CardContent className="flex-1 flex items-center justify-center">
          <LoadingSpinner size="lg" />
        </CardContent>
      </Card>
    )
  }

  // Show error state if data fetch failed (unlikely but good to handle)
  if (!sources && !notes) {
    return (
      <Card className="h-full flex flex-col">
        <CardContent className="flex-1 flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            <AlertCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p className="text-sm">{t.chat.unableToLoadChat}</p>
            <p className="text-xs mt-2">{t.common.refreshPage || 'Please try refreshing the page'}</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="h-full min-h-0 flex gap-3">
      {/* Persistent session sidebar (ChatGPT-style), consistent with global chat.
          Collapsed by default here because the notebook chat lives in a narrow
          column; the toggle expands/collapses it. */}
      {sidebarOpen ? (
        <div className="w-56 flex-shrink-0 flex flex-col rounded-lg border bg-card/40 min-h-0">
          <div className="flex items-center justify-end px-2 pt-2">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setSidebarOpen(false)}
              title={t.common.collapse ?? 'Recolher'}
            >
              <PanelLeftClose className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex-1 min-h-0">
            <SessionManager
              variant="sidebar"
              sessions={chat.sessions}
              currentSessionId={chat.currentSessionId}
              onNewChat={() => chat.newConversation()}
              newChatDisabled={!chat.currentSessionId && chat.messages.length === 0}
              onCreateSession={(title) => chat.createSession(title)}
              onSelectSession={chat.switchSession}
              onUpdateSession={(sessionId, title) => chat.updateSession(sessionId, { title })}
              onDeleteSession={chat.deleteSession}
              loadingSessions={chat.loadingSessions}
            />
          </div>
        </div>
      ) : (
        <div className="flex-shrink-0 pt-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setSidebarOpen(true)}
            title={t.chat.sessions}
          >
            <PanelLeftOpen className="h-4 w-4" />
          </Button>
        </div>
      )}

      <div className="flex-1 min-h-0">
        <ChatPanel
          title={t.chat.chatWithNotebook}
          contextType="notebook"
          messages={chat.messages}
          isStreaming={chat.isSending}
          contextIndicators={null}
          onSendMessage={(message, modelOverride, file, deepResearch, agentOptions) => chat.sendMessage(message, modelOverride, file, deepResearch, agentOptions)}
          onReviseReport={chat.reviseReport}
          modelOverride={chat.currentSession?.model_override ?? chat.pendingModelOverride ?? undefined}
          onModelChange={(model) => chat.setModelOverride(model ?? null)}
          notebookContextStats={contextStats}
          notebookId={notebookId}
          enableAttachments
          enableDeepResearch
          enableAgentControls
          isDeepResearchSession={chat.isDeepResearchSession}
        />
      </div>
    </div>
  )
}
