'use client'

import { useState, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import {
  MessageSquare,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
  Clock,
  Search
} from 'lucide-react'
import { formatDistanceToNow, isToday, isYesterday, differenceInCalendarDays } from 'date-fns'
import { getDateLocale } from '@/lib/utils/date-locale'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { BaseChatSession } from '@/lib/types/api'
import { useModels } from '@/lib/hooks/use-models'

interface SessionManagerProps {
  sessions: BaseChatSession[]
  currentSessionId: string | null
  onCreateSession: (title: string) => void
  onSelectSession: (sessionId: string) => void
  onUpdateSession: (sessionId: string, title: string) => void
  onDeleteSession: (sessionId: string) => void
  loadingSessions: boolean
  // "panel" (default) renders the boxed card used inside the Sessions tab.
  // "sidebar" renders a ChatGPT-style persistent left column with a prominent
  // "New chat" button and no card chrome.
  variant?: 'panel' | 'sidebar'
  // Optional: start a brand-new chat (sidebar "New chat" button). Falls back to
  // creating a default-titled session when not provided.
  onNewChat?: () => void
  // Disable the sidebar "New chat" button when the current conversation is
  // already empty, so repeated clicks don't spawn redundant empty sessions.
  newChatDisabled?: boolean
}

export function SessionManager({
  sessions,
  currentSessionId,
  onCreateSession,
  onSelectSession,
  onUpdateSession,
  onDeleteSession,
  loadingSessions,
  variant = 'panel',
  onNewChat,
  newChatDisabled = false,
}: SessionManagerProps) {
  const isSidebar = variant === 'sidebar'
  const { t, language } = useTranslation()
  const [isCreating, setIsCreating] = useState(false)
  const [newSessionTitle, setNewSessionTitle] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const { data: models } = useModels()

  // Filter by the search box, then bucket sessions by recency (ChatGPT-style).
  const sessionGroups = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    const filtered = query
      ? sessions.filter((s) => (s.title || '').toLowerCase().includes(query))
      : sessions

    const buckets: { key: string; label: string; items: BaseChatSession[] }[] = [
      { key: 'today', label: t.chat.groupToday ?? 'Hoje', items: [] },
      { key: 'yesterday', label: t.chat.groupYesterday ?? 'Ontem', items: [] },
      { key: 'week', label: t.chat.groupPrevious7Days ?? 'Últimos 7 dias', items: [] },
      { key: 'month', label: t.chat.groupPrevious30Days ?? 'Últimos 30 dias', items: [] },
      { key: 'older', label: t.chat.groupOlder ?? 'Mais antigas', items: [] },
    ]

    // Most recently updated first within each bucket.
    const sorted = [...filtered].sort(
      (a, b) => new Date(b.updated || b.created).getTime() - new Date(a.updated || a.created).getTime(),
    )

    for (const session of sorted) {
      const date = new Date(session.updated || session.created)
      const days = differenceInCalendarDays(new Date(), date)
      if (isToday(date)) buckets[0].items.push(session)
      else if (isYesterday(date)) buckets[1].items.push(session)
      else if (days <= 7) buckets[2].items.push(session)
      else if (days <= 30) buckets[3].items.push(session)
      else buckets[4].items.push(session)
    }

    return buckets.filter((b) => b.items.length > 0)
  }, [sessions, searchQuery, t])

  // Helper to get model name from ID
  const customModelLabel = t.common.customModel
  const getModelName = useMemo(() => {
    return (modelId: string) => {
      const model = models?.find(m => m.id === modelId)
      return model?.name || customModelLabel
    }
  }, [models, customModelLabel])

  const handleCreateSession = () => {
    if (newSessionTitle.trim()) {
      onCreateSession(newSessionTitle.trim())
      setNewSessionTitle('')
      setIsCreating(false)
    }
  }

  const handleStartEdit = (session: BaseChatSession) => {
    setEditingId(session.id)
    setEditTitle(session.title)
  }

  const handleSaveEdit = () => {
    if (editingId && editTitle.trim()) {
      onUpdateSession(editingId, editTitle.trim())
      setEditingId(null)
      setEditTitle('')
    }
  }

  const handleCancelEdit = () => {
    setEditingId(null)
    setEditTitle('')
  }

  const handleDeleteConfirm = () => {
    if (deleteConfirmId) {
      onDeleteSession(deleteConfirmId)
      setDeleteConfirmId(null)
    }
  }

  return (
    <>
      <Card
        className={
          isSidebar
            ? 'h-full flex flex-col border-0 bg-transparent shadow-none rounded-none'
            : 'h-full flex flex-col'
        }
      >
        <CardHeader className={isSidebar ? 'gap-2 px-3 pb-2 pt-3' : 'pb-3 pr-12'}>
          {isSidebar ? (
            <Button
              className="w-full justify-start gap-2"
              disabled={newChatDisabled}
              onClick={() => (onNewChat ? onNewChat() : onCreateSession(t.chat.newChat ?? 'Nova conversa'))}
            >
              <Plus className="h-4 w-4" />
              {t.chat.newChat ?? 'Nova conversa'}
            </Button>
          ) : (
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center gap-2">
                <MessageSquare className="h-5 w-5" />
                {t.chat.sessions}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setIsCreating(true)}
                className="ml-4"
              >
                <Plus className="h-4 w-4 mr-1" />
                <span className="text-xs">{t.common.create}</span>
              </Button>
            </CardTitle>
          )}
          {sessions.length > 0 && (
            <div className={`relative ${isSidebar ? '' : 'mt-2'}`}>
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t.chat.searchSessions ?? 'Procurar conversas...'}
                className="h-8 pl-8 text-sm"
              />
            </div>
          )}
        </CardHeader>
        <CardContent className={isSidebar ? 'flex-1 p-0 min-h-0' : 'flex-1 p-0 min-h-0'}>
          <ScrollArea className="h-full px-4">
            {isCreating && (
              <div className="p-3 border rounded-lg mb-3">
                <Input
                  value={newSessionTitle}
                  onChange={(e) => setNewSessionTitle(e.target.value)}
                  placeholder={t.chat.sessionTitlePlaceholder}
                  className="mb-2"
                  autoFocus
                  onKeyPress={(e) => {
                    if (e.key === 'Enter') handleCreateSession()
                  }}
                />
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleCreateSession}>
                    {t.common.create}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setIsCreating(false)
                      setNewSessionTitle('')
                    }}
                  >
                    {t.common.cancel}
                  </Button>
                </div>
              </div>
            )}

            {loadingSessions ? (
              <div className="text-center py-8 text-muted-foreground">
                {t.common.loading}
              </div>
            ) : sessions.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <MessageSquare className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p className="text-sm">{t.chat.noSessions}</p>
                <p className="text-xs mt-2">{t.chat.createToStart}</p>
              </div>
            ) : sessionGroups.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <p className="text-sm">{t.common.noResults ?? 'Sem resultados'}</p>
              </div>
            ) : (
              <div className="space-y-4 pb-4">
                {sessionGroups.map((group) => (
                  <div key={group.key} className="space-y-1">
                    <div className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {group.label}
                    </div>
                    {group.items.map((session) => (
                  <div
                    key={session.id}
                    className={`group p-3 rounded-lg border cursor-pointer transition-colors ${
                      currentSessionId === session.id
                        ? 'bg-primary/10 border-primary'
                        : 'border-transparent hover:bg-muted'
                    }`}
                    onClick={() => onSelectSession(session.id)}
                  >
                    {editingId === session.id ? (
                      <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                        <Input
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onKeyPress={(e) => {
                            if (e.key === 'Enter') handleSaveEdit()
                            if (e.key === 'Escape') handleCancelEdit()
                          }}
                          autoFocus
                        />
                        <div className="flex gap-2">
                          <Button size="sm" onClick={handleSaveEdit}>
                            <Check className="h-3 w-3" />
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={handleCancelEdit}
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-start justify-between mb-1">
                          <h4 className="font-medium text-sm flex-1 mr-2">
                            {session.title}
                          </h4>
                          <div
                            className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 w-7 p-0"
                              onClick={() => handleStartEdit(session)}
                            >
                              <Edit2 className="h-3 w-3" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                              onClick={() => setDeleteConfirmId(session.id)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Clock className="h-3 w-3" />
                          {formatDistanceToNow(new Date(session.created), {
                            addSuffix: true,
                            locale: getDateLocale(language)
                          })}
                        </div>
                        {session.message_count != null && session.message_count > 0 && (
                          <Badge variant="secondary" className="mt-2 text-xs">
                            {t.chat.messagesCount.replace('{count}', session.message_count.toString())}
                          </Badge>
                        )}
                        {session.model_override && (
                          <Badge variant="outline" className="mt-2 ml-2 text-xs">
                            {getModelName(session.model_override)}
                          </Badge>
                        )}
                      </>
                    )}
                  </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </CardContent>
      </Card>

      <AlertDialog open={!!deleteConfirmId} onOpenChange={() => setDeleteConfirmId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.chat.deleteSession}</AlertDialogTitle>
            <AlertDialogDescription>
              {t.chat.deleteSessionDesc}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.common.cancel}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteConfirm}>
              {t.common.delete}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}