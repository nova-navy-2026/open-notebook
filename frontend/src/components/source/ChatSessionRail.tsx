'use client'

import { useMemo, useState } from 'react'
import { differenceInCalendarDays } from 'date-fns'
import {
  Plus,
  Search,
  MessageSquare,
  PanelLeft,
  PanelLeftClose,
  MoreHorizontal,
  Pencil,
  Trash2,
  Check,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
import { useTranslation } from '@/lib/hooks/use-translation'

interface ChatSessionRailProps {
  sessions: BaseChatSession[]
  currentSessionId: string | null
  loading: boolean
  collapsed: boolean
  onToggleCollapsed: () => void
  onNewChat: () => void
  onSelectSession: (sessionId: string) => void
  onRenameSession: (sessionId: string, title: string) => void
  onDeleteSession: (sessionId: string) => void
}

type GroupKey = 'today' | 'yesterday' | 'prev7' | 'prev30' | 'older'

const GROUP_ORDER: GroupKey[] = ['today', 'yesterday', 'prev7', 'prev30', 'older']

function groupForDate(value: string, now: Date): GroupKey {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'older'
  const days = differenceInCalendarDays(now, date)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days <= 7) return 'prev7'
  if (days <= 30) return 'prev30'
  return 'older'
}

function sessionTime(session: BaseChatSession): number {
  const value = session.updated || session.created
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

export function ChatSessionRail({
  sessions,
  currentSessionId,
  loading,
  collapsed,
  onToggleCollapsed,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
}: ChatSessionRailProps) {
  const { t } = useTranslation()
  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  const groupLabels: Record<GroupKey, string> = {
    today: t.chat.groupToday ?? 'Today',
    yesterday: t.chat.groupYesterday ?? 'Yesterday',
    prev7: t.chat.groupPrevious7Days ?? 'Previous 7 days',
    prev30: t.chat.groupPrevious30Days ?? 'Previous 30 days',
    older: t.chat.groupOlder ?? 'Older',
  }

  // Filter by search, then bucket into recency groups (most recent first).
  const groupedSessions = useMemo(() => {
    const now = new Date()
    const query = search.trim().toLowerCase()
    const filtered = query
      ? sessions.filter((s) => s.title?.toLowerCase().includes(query))
      : sessions
    const sorted = [...filtered].sort((a, b) => sessionTime(b) - sessionTime(a))

    const buckets = new Map<GroupKey, BaseChatSession[]>()
    for (const session of sorted) {
      const key = groupForDate(session.updated || session.created, now)
      const bucket = buckets.get(key)
      if (bucket) bucket.push(session)
      else buckets.set(key, [session])
    }
    return GROUP_ORDER.flatMap((key) => {
      const items = buckets.get(key)
      return items && items.length ? [{ key, label: groupLabels[key], items }] : []
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions, search])

  const startEdit = (session: BaseChatSession) => {
    setEditingId(session.id)
    setEditTitle(session.title)
  }

  const saveEdit = () => {
    if (editingId && editTitle.trim()) {
      onRenameSession(editingId, editTitle.trim())
    }
    setEditingId(null)
    setEditTitle('')
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditTitle('')
  }

  // Collapsed: a slim icon strip (New chat + expand), echoing the global rail.
  if (collapsed) {
    return (
      <TooltipProvider delayDuration={0}>
        <div className="flex h-full w-12 flex-shrink-0 flex-col items-center gap-2 border-r border-sidebar-border bg-sidebar py-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={onToggleCollapsed}
                className="text-sidebar-foreground hover:bg-sidebar-accent"
                aria-label={t.chat.showChatHistory ?? 'Show chat history'}
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">
              {t.chat.showChatHistory ?? 'Show chat history'}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="default"
                size="icon"
                onClick={onNewChat}
                className="bg-primary text-primary-foreground hover:bg-primary/90"
                aria-label={t.chat.newChat ?? 'New chat'}
              >
                <Plus className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">{t.chat.newChat ?? 'New chat'}</TooltipContent>
          </Tooltip>
        </div>
      </TooltipProvider>
    )
  }

  return (
    <TooltipProvider delayDuration={0}>
      <div className="flex h-full w-64 flex-shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
        {/* Header: New chat + collapse toggle */}
        <div className="flex items-center gap-2 p-3">
          <Button
            variant="default"
            size="sm"
            onClick={onNewChat}
            className="flex-1 justify-start gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            {t.chat.newChat ?? 'New chat'}
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={onToggleCollapsed}
                className="flex-shrink-0 text-sidebar-foreground hover:bg-sidebar-accent"
                aria-label={t.chat.hideChatHistory ?? 'Hide chat history'}
              >
                <PanelLeftClose className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">
              {t.chat.hideChatHistory ?? 'Hide chat history'}
            </TooltipContent>
          </Tooltip>
        </div>

        {/* Search */}
        <div className="px-3 pb-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-sidebar-foreground/50" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t.chat.searchChats ?? 'Search chats...'}
              className="h-8 border-sidebar-border bg-sidebar pl-8 text-sm text-sidebar-foreground placeholder:text-sidebar-foreground/50"
            />
          </div>
        </div>

        {/* Session list, grouped by recency */}
        <ScrollArea className="min-h-0 flex-1 px-2">
          {loading ? (
            <div className="py-8 text-center text-sm text-sidebar-foreground/60">
              {t.common.loading}
            </div>
          ) : groupedSessions.length === 0 ? (
            <div className="px-2 py-8 text-center text-sidebar-foreground/60">
              <MessageSquare className="mx-auto mb-3 h-10 w-10 opacity-40" />
              <p className="text-sm">
                {search.trim()
                  ? t.chat.noChatsFound ?? 'No chats match your search'
                  : t.chat.noSessions ?? 'No chat sessions yet'}
              </p>
            </div>
          ) : (
            <div className="pb-4">
              {groupedSessions.map((group) => (
                <div key={group.key} className="mb-2">
                  <h3 className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/50">
                    {group.label}
                  </h3>
                  <div className="space-y-0.5">
                    {group.items.map((session) => {
                      const isActive = session.id === currentSessionId
                      const isEditing = session.id === editingId

                      if (isEditing) {
                        return (
                          <div
                            key={session.id}
                            className="flex items-center gap-1 rounded-md bg-sidebar-accent px-1.5 py-1"
                          >
                            <Input
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') saveEdit()
                                if (e.key === 'Escape') cancelEdit()
                              }}
                              autoFocus
                              className="h-7 bg-background text-sm"
                            />
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 flex-shrink-0"
                              onClick={saveEdit}
                            >
                              <Check className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 flex-shrink-0"
                              onClick={cancelEdit}
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        )
                      }

                      return (
                        <div
                          key={session.id}
                          className={cn(
                            'group/session flex items-center gap-1 rounded-md px-2 py-1.5 text-sm transition-colors',
                            isActive
                              ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                              : 'text-sidebar-foreground hover:bg-sidebar-accent/60',
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => onSelectSession(session.id)}
                            className="min-w-0 flex-1 truncate text-left"
                            title={session.title}
                          >
                            {session.title}
                          </button>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className={cn(
                                  'h-6 w-6 flex-shrink-0 opacity-0 transition-opacity focus-visible:opacity-100 group-hover/session:opacity-100',
                                  isActive && 'opacity-70',
                                )}
                                aria-label={t.common.edit}
                              >
                                <MoreHorizontal className="h-4 w-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-40">
                              <DropdownMenuItem onClick={() => startEdit(session)}>
                                <Pencil className="mr-2 h-4 w-4" />
                                {t.chat.renameChat ?? t.common.edit}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                className="text-destructive focus:text-destructive"
                                onClick={() => setDeleteConfirmId(session.id)}
                              >
                                <Trash2 className="mr-2 h-4 w-4" />
                                {t.common.delete}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>

      <AlertDialog
        open={!!deleteConfirmId}
        onOpenChange={(open) => !open && setDeleteConfirmId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.chat.deleteSession}</AlertDialogTitle>
            <AlertDialogDescription>{t.chat.deleteSessionDesc}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.common.cancel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (deleteConfirmId) onDeleteSession(deleteConfirmId)
                setDeleteConfirmId(null)
              }}
            >
              {t.common.delete}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </TooltipProvider>
  )
}
