'use client'

import { useState, useRef, useEffect, useId, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Bot, User, Send, Loader2, FileText, Lightbulb, StickyNote, MessageSquare, Clock, Paperclip, X, Image as ImageIcon, Video, AudioLines, Search, Download, Copy, Table2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { conversationToMarkdown, downloadMarkdown } from '@/lib/utils/export-markdown'
import {
  SourceChatMessage,
  SourceChatContextIndicator,
  BaseChatSession
} from '@/lib/types/api'
import { ModelSelector as ChatModelSelector } from './ModelSelector'
import { ModelSelector as InlineModelSelector } from '@/components/common/ModelSelector'
import { ContextIndicator } from '@/components/common/ContextIndicator'
import { SessionManager } from '@/components/source/SessionManager'
import { MessageActions } from '@/components/source/MessageActions'
import { convertReferencesToCompactMarkdown, createCompactReferenceLinkComponent } from '@/lib/utils/source-references'
import { useModalManager } from '@/lib/hooks/use-modal-manager'
import { toast } from 'sonner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useReportTypes, useResearchTones } from '@/lib/hooks/use-research'
import { useModelDefaults } from '@/lib/hooks/use-models'
import { notebooksApi } from '@/lib/api/notebooks'
import { getAttachmentKind, isAudioLikeFile, isVideoLikeFile, isVisualLikeFile } from '@/lib/utils/file-kind'
import type { ChatAgentUiOptions, ChatDeepResearchOptions } from '@/lib/utils/chat-agents'

interface NotebookContextStats {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount?: number
  charCount?: number
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface ChatPanelProps {
  messages: SourceChatMessage[]
  isStreaming: boolean
  contextIndicators: SourceChatContextIndicator | null
  onSendMessage: (
    message: string,
    modelOverride?: string,
    file?: File,
    deepResearch?: ChatDeepResearchOptions,
    agentOptions?: ChatAgentUiOptions,
  ) => void
  modelOverride?: string
  onModelChange?: (model?: string) => void
  // Session management props
  sessions?: BaseChatSession[]
  currentSessionId?: string | null
  onCreateSession?: (title: string) => void
  onSelectSession?: (sessionId: string) => void
  onDeleteSession?: (sessionId: string) => void
  onUpdateSession?: (sessionId: string, title: string) => void
  loadingSessions?: boolean
  // Generic props for reusability
  title?: string
  contextType?: 'source' | 'notebook'
  // Notebook context stats (for notebook chat)
  notebookContextStats?: NotebookContextStats
  // Notebook ID for saving notes
  notebookId?: string
  enableAttachments?: boolean
  visualModelLocked?: boolean
  enableDeepResearch?: boolean
  enableAgentControls?: boolean
  // Export all conversations (optional). When provided, an "Export all" item is shown.
  onExportAll?: () => void | Promise<void>
  exportingAll?: boolean
}

export function ChatPanel({
  messages,
  isStreaming,
  contextIndicators,
  onSendMessage,
  modelOverride,
  onModelChange,
  sessions = [],
  currentSessionId,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onUpdateSession,
  loadingSessions = false,
  title,
  contextType = 'source',
  notebookContextStats,
  notebookId,
  enableAttachments = false,
  visualModelLocked = false,
  enableDeepResearch = false,
  enableAgentControls = false,
  onExportAll,
  exportingAll = false,
}: ChatPanelProps) {
  const { t } = useTranslation()
  const chatInputId = useId()
  const [input, setInput] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [deepResearchEnabled, setDeepResearchEnabled] = useState(false)
  const [researchReportType, setResearchReportType] = useState('research_report')
  const [researchTone, setResearchTone] = useState('Objective')
  const [researchModelId, setResearchModelId] = useState('')
  const [transcriptionLanguage, setTranscriptionLanguage] = useState('auto')
  const [transcriptionDiarize, setTranscriptionDiarize] = useState(false)
  const [transcriptionSpeakers, setTranscriptionSpeakers] = useState('auto')
  const [visionEngine, setVisionEngine] = useState<'auto' | 'sam3' | 'rfdetr'>('auto')
  const [visionMode, setVisionMode] = useState<'auto' | 'describe' | 'ocr' | 'detect' | 'track'>('auto')
  const [saveNoteNotebookId, setSaveNoteNotebookId] = useState('')
  const [activeTab, setActiveTab] = useState<'chat' | 'sessions'>('chat')
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { openModal } = useModalManager()
  const { data: reportTypes = [] } = useReportTypes()
  const { data: tones = [] } = useResearchTones()
  const { data: modelDefaults } = useModelDefaults()
  const { data: availableNotebooks = [] } = useQuery({
    queryKey: ['chat-agent-notebooks'],
    queryFn: () => notebooksApi.list({ archived: false }),
    enabled: enableAgentControls && !notebookId,
  })
  const selectedFileKind = getAttachmentKind(selectedFile)
  const selectedFileIsVisual = isVisualLikeFile(selectedFile)
  const selectedFileIsAudio = isAudioLikeFile(selectedFile)
  const isVisualModelLocked = enableAttachments && (visualModelLocked || selectedFileIsVisual)
  const canUseDeepResearch = enableDeepResearch && !selectedFile
  const showTranscriptionControls = enableAgentControls && !!selectedFile && (
    selectedFileIsAudio || isVideoLikeFile(selectedFile)
  )
  const showVisionControls = enableAgentControls && selectedFileIsVisual
  const showSaveNoteControls = enableAgentControls && !notebookId && !selectedFile && availableNotebooks.length > 1
  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const scrollRoot = scrollAreaRef.current
    const viewport = scrollRoot?.querySelector('[data-radix-scroll-area-viewport]') as HTMLDivElement | null

    const run = () => {
      if (viewport) {
        viewport.scrollTo({ top: viewport.scrollHeight, behavior })
      } else {
        messagesEndRef.current?.scrollIntoView({ behavior, block: 'end' })
      }
    }

    requestAnimationFrame(run)
    window.setTimeout(run, 80)
    window.setTimeout(run, 240)
  }, [])

  const handleReferenceClick = (type: string, id: string) => {
    const modalType = type === 'source_insight' ? 'insight' : type as 'source' | 'note' | 'insight'

    try {
      openModal(modalType, id)
      // Note: The modal system uses URL parameters and doesn't throw errors for missing items.
      // The modal component itself will handle displaying "not found" states.
      // This try-catch is here for future enhancements or unexpected errors.
    } catch {
      toast.error(t.common.noResults)
    }
  }

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    scrollToBottom('smooth')
  }, [messages, isStreaming, scrollToBottom])

  useEffect(() => {
    if (!researchModelId && modelDefaults?.default_chat_model) {
      setResearchModelId(modelDefaults.default_chat_model)
    }
  }, [modelDefaults?.default_chat_model, researchModelId])

  const handleSend = () => {
    if ((input.trim() || selectedFile) && !isStreaming) {
      const deepResearch = canUseDeepResearch && deepResearchEnabled
        ? {
          reportType: researchReportType,
          tone: researchTone,
          modelId: researchModelId || undefined,
        }
        : undefined
      onSendMessage(
        input.trim() || 'Analisa este ficheiro.',
        modelOverride,
        deepResearch ? undefined : selectedFile ?? undefined,
        deepResearch,
        {
          transcription: showTranscriptionControls
            ? {
              language: transcriptionLanguage === 'auto' ? undefined : transcriptionLanguage,
              diarize: transcriptionDiarize,
              numSpeakers: transcriptionSpeakers === 'auto'
                ? undefined
                : Number(transcriptionSpeakers),
            }
            : undefined,
          vision: showVisionControls
            ? { engine: visionEngine, mode: visionMode }
            : undefined,
          saveNote: saveNoteNotebookId
            ? { notebookId: saveNoteNotebookId }
            : undefined,
        },
      )
      setInput('')
      setSelectedFile(null)
      if (deepResearch) {
        setDeepResearchEnabled(false)
      }
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null
    if (file) {
      setSelectedFile(file)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Detect platform for correct modifier key
    const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
    const isModifierPressed = isMac ? e.metaKey : e.ctrlKey

    if (e.key === 'Enter' && isModifierPressed) {
      e.preventDefault()
      handleSend()
    }
  }

  // Detect platform for placeholder text
  const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
  const keyHint = isMac ? '⌘+Enter' : 'Ctrl+Enter'

  const hasSessions = onSelectSession && onCreateSession && onDeleteSession

  const resolvedTitle = title || (contextType === 'source'
    ? t.chat.chatWith.replace('{name}', t.navigation.sources)
    : t.chat.chatWith.replace('{name}', t.common.notebook))

  const handleExportCurrent = useCallback(() => {
    if (!messages.length) {
      toast.info(t.chat.noMessagesToExport ?? 'Não há mensagens para exportar')
      return
    }
    const markdown = conversationToMarkdown({
      title: resolvedTitle,
      messages,
    })
    downloadMarkdown(markdown, resolvedTitle)
    toast.success(t.chat.conversationExported ?? 'Conversa exportada')
  }, [messages, resolvedTitle, t])

  const exportMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 flex-shrink-0"
          title={t.chat.exportConversation ?? 'Exportar conversa'}
          disabled={exportingAll}
        >
          {exportingAll ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={handleExportCurrent}>
          <Download className="mr-2 h-4 w-4" />
          {t.chat.exportCurrentConversation ?? 'Exportar conversa atual'}
        </DropdownMenuItem>
        {onExportAll && (
          <DropdownMenuItem onClick={() => void onExportAll()} disabled={exportingAll}>
            <Download className="mr-2 h-4 w-4" />
            {t.chat.exportAllConversations ?? 'Exportar todas as conversas'}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )

  return (
    <>
    <Card className="flex flex-col h-full flex-1 overflow-hidden">
      <CardHeader className="pb-3 flex-shrink-0">
        {hasSessions ? (
          <div className="flex items-center gap-2">
            <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'chat' | 'sessions')} className="flex-1 min-w-0">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="chat" className="gap-1.5">
                  <MessageSquare className="h-4 w-4" />
                  <span className="truncate">{title || t.common.chat}</span>
                </TabsTrigger>
                <TabsTrigger value="sessions" className="gap-1.5">
                  <Clock className="h-4 w-4" />
                  {t.chat.sessions}
                </TabsTrigger>
              </TabsList>
            </Tabs>
            {exportMenu}
          </div>
        ) : (
          <div className="flex items-center gap-2 min-w-0">
            <CardTitle className="flex items-center gap-2 truncate min-w-0 flex-1">
              <Bot className="h-5 w-5 flex-shrink-0" />
              <span className="truncate">{resolvedTitle}</span>
            </CardTitle>
            {exportMenu}
          </div>
        )}
      </CardHeader>

      {/* Sessions Tab Content */}
      {hasSessions && activeTab === 'sessions' ? (
        <CardContent className="flex-1 min-h-0 p-0 overflow-hidden">
          <SessionManager
            sessions={sessions}
            currentSessionId={currentSessionId ?? null}
            onCreateSession={(title) => onCreateSession?.(title)}
            onSelectSession={(sessionId) => {
              onSelectSession(sessionId)
              setActiveTab('chat')
            }}
            onUpdateSession={(sessionId, title) => onUpdateSession?.(sessionId, title)}
            onDeleteSession={(sessionId) => onDeleteSession?.(sessionId)}
            loadingSessions={loadingSessions}
          />
        </CardContent>
      ) : (
      <CardContent className="flex-1 flex flex-col min-h-0 p-0">
        <ScrollArea className="flex-1 min-h-0 px-4" ref={scrollAreaRef}>
          <div className="space-y-4 py-4">
            {messages.length === 0 ? (
              <div className="text-center text-muted-foreground py-8">
                <Bot className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p className="text-sm">
                  {t.chat.startConversation.replace('{type}', contextType === 'source' ? t.navigation.sources : t.common.notebook)}
                </p>
                <p className="text-xs mt-2">{t.chat.askQuestions}</p>
              </div>
            ) : (
              messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex gap-3 ${
                    message.type === 'human' ? 'justify-end' : 'justify-start'
                  }`}
                >
                  {message.type === 'ai' && (
                    <div className="flex-shrink-0">
                      <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                        <Bot className="h-4 w-4" />
                      </div>
                    </div>
                  )}
                  <div className="flex flex-col gap-2 max-w-[80%]">
                    {message.type === 'human' && message.attachments?.length ? (
                      <div className="flex justify-end">
                        {message.attachments.map((attachment) => (
                          <div key={attachment.url} className="max-w-48 overflow-hidden rounded-md border bg-background">
                            {attachment.kind === 'image' ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={attachment.url}
                                alt={attachment.name}
                                className="max-h-36 w-full object-contain"
                                onLoad={() => scrollToBottom('auto')}
                              />
                            ) : attachment.kind === 'video' ? (
                              <video
                                src={attachment.url}
                                controls
                                className="max-h-36 w-full bg-black"
                                onLoadedMetadata={() => scrollToBottom('auto')}
                              />
                            ) : attachment.kind === 'audio' ? (
                              <audio
                                src={attachment.url}
                                controls
                                className="w-48"
                              />
                            ) : (
                              <div className="px-3 py-2 text-xs">{attachment.name}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : null}
                    <div
                      className={`rounded-lg px-4 py-2 ${
                        message.type === 'human'
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted'
                      }`}
                    >
                      {message.type === 'ai' ? (
                        <AIMessageContent
                          content={message.content}
                          onReferenceClick={handleReferenceClick}
                          onMediaLoad={() => scrollToBottom('auto')}
                        />
                      ) : (
                        <p className="text-sm break-all">{message.content}</p>
                      )}
                    </div>
                    {message.type === 'ai' && (
                      <MessageActions
                        content={message.content}
                        notebookId={notebookId}
                      />
                    )}
                  </div>
                  {message.type === 'human' && (
                    <div className="flex-shrink-0">
                      <div className="h-8 w-8 rounded-full bg-primary flex items-center justify-center">
                        <User className="h-4 w-4 text-primary-foreground" />
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
            {isStreaming && (
              <div className="flex gap-3 justify-start">
                <div className="flex-shrink-0">
                  <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                    <Bot className="h-4 w-4" />
                  </div>
                </div>
                <div className="rounded-lg px-4 py-2 bg-muted">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        {/* Context Indicators */}
        {contextIndicators && (
          <div className="border-t px-4 py-2">
            <div className="flex flex-wrap gap-2 text-xs">
              {contextIndicators.sources?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <FileText className="h-3 w-3" />
                  {contextIndicators.sources.length} {t.navigation.sources}
                </Badge>
              )}
              {contextIndicators.insights?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <Lightbulb className="h-3 w-3" />
                  {contextIndicators.insights.length} {contextIndicators.insights.length === 1 ? t.common.insight : t.common.insights}
                </Badge>
              )}
              {contextIndicators.notes?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <StickyNote className="h-3 w-3" />
                  {contextIndicators.notes.length} {contextIndicators.notes.length === 1 ? t.common.note : t.common.notes}
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* Notebook Context Indicator */}
        {notebookContextStats && (
          <ContextIndicator
            sourcesInsights={notebookContextStats.sourcesInsights}
            sourcesFull={notebookContextStats.sourcesFull}
            notesCount={notebookContextStats.notesCount}
            tokenCount={notebookContextStats.tokenCount}
            charCount={notebookContextStats.charCount}
          />
        )}

        {/* Input Area */}
        <div className="flex-shrink-0 p-4 space-y-3 border-t">
          {/* Model selector */}
          {onModelChange && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">{t.chat.model}</span>
              <ChatModelSelector
                currentModel={modelOverride}
                onModelChange={onModelChange}
                disabled={isStreaming || isVisualModelLocked}
                displayNameOverride={isVisualModelLocked ? 'Gemma' : undefined}
                locked={isVisualModelLocked}
                lockedReason={
                  isVisualModelLocked
                    ? 'Os pedidos com imagem ou vídeo usam automaticamente a Gemma multimodal.'
                    : undefined
                }
              />
            </div>
          )}

          {enableDeepResearch && (
            <div className="space-y-2 rounded-md border bg-muted/20 p-2">
              <div className="flex items-center justify-between gap-2">
                <Button
                  type="button"
                  variant={deepResearchEnabled ? 'default' : 'outline'}
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => setDeepResearchEnabled((enabled) => !enabled)}
                  disabled={isStreaming || !!selectedFile}
                  title={selectedFile ? 'Deep Research usa apenas pedidos de texto.' : undefined}
                >
                  <Search className="h-4 w-4" />
                  Deep Research
                </Button>
              </div>

              {deepResearchEnabled && canUseDeepResearch && (
                <div className="grid gap-2 sm:grid-cols-3">
                  <div className="space-y-1">
                    <Label className="text-xs">{t.research?.reportType ?? 'Report Type'}</Label>
                    <Select
                      value={researchReportType}
                      onValueChange={setResearchReportType}
                      disabled={isStreaming}
                    >
                      <SelectTrigger className="h-8">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {reportTypes.map((reportType) => (
                          <SelectItem key={reportType.value} value={reportType.value}>
                            {reportType.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1">
                    <Label className="text-xs">{t.research?.toneLabel ?? 'Writing Tone'}</Label>
                    <Select
                      value={researchTone}
                      onValueChange={setResearchTone}
                      disabled={isStreaming}
                    >
                      <SelectTrigger className="h-8">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {tones.map((tone) => (
                          <SelectItem key={tone.value} value={tone.value}>
                            {tone.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1">
                    <Label className="text-xs">{t.research?.modelLabel ?? 'AI Model'}</Label>
                    <InlineModelSelector
                      modelType="language"
                      value={researchModelId}
                      onChange={setResearchModelId}
                      placeholder={t.research?.selectModelPlaceholder ?? 'Select a model...'}
                      disabled={isStreaming}
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {enableAgentControls && (showTranscriptionControls || showVisionControls || showSaveNoteControls) && (
            <div className="grid gap-2 rounded-md border bg-muted/20 p-2 sm:grid-cols-3">
              {showTranscriptionControls && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Idioma</Label>
                    <Select value={transcriptionLanguage} onValueChange={setTranscriptionLanguage} disabled={isStreaming}>
                      <SelectTrigger className="h-8">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="auto">Auto</SelectItem>
                        <SelectItem value="pt">Português</SelectItem>
                        <SelectItem value="en">English</SelectItem>
                        <SelectItem value="es">Español</SelectItem>
                        <SelectItem value="fr">Français</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1">
                    <Label className="text-xs">Oradores</Label>
                    <Select value={transcriptionSpeakers} onValueChange={setTranscriptionSpeakers} disabled={isStreaming || !transcriptionDiarize}>
                      <SelectTrigger className="h-8">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="auto">Auto</SelectItem>
                        {[1, 2, 3, 4, 5, 6].map((count) => (
                          <SelectItem key={count} value={String(count)}>
                            {count}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <label className="flex h-8 items-center gap-2 self-end text-xs">
                    <Checkbox
                      checked={transcriptionDiarize}
                      onCheckedChange={(checked) => setTranscriptionDiarize(Boolean(checked))}
                      disabled={isStreaming}
                    />
                    Diarizar
                  </label>
                </>
              )}

              {showVisionControls && (
                <>
                <div className="space-y-1">
                  <Label className="text-xs">Modo visual</Label>
                  <Select value={visionMode} onValueChange={(value) => setVisionMode(value as 'auto' | 'describe' | 'ocr' | 'detect' | 'track')} disabled={isStreaming}>
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Auto</SelectItem>
                      <SelectItem value="describe">Descrever</SelectItem>
                      <SelectItem value="ocr">OCR</SelectItem>
                      <SelectItem value="detect">Detetar</SelectItem>
                      <SelectItem value="track">Seguir</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Motor</Label>
                  <Select value={visionEngine} onValueChange={(value) => setVisionEngine(value as 'auto' | 'sam3' | 'rfdetr')} disabled={isStreaming}>
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Auto</SelectItem>
                      <SelectItem value="sam3">SAM3</SelectItem>
                      <SelectItem value="rfdetr">RF-DETR</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                </>
              )}

              {showSaveNoteControls && (
                <div className="space-y-1 sm:col-span-2">
                  <Label className="text-xs">Guardar notas em</Label>
                  <Select value={saveNoteNotebookId || 'auto'} onValueChange={(value) => setSaveNoteNotebookId(value === 'auto' ? '' : value)} disabled={isStreaming}>
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Perguntar automaticamente</SelectItem>
                      {availableNotebooks.map((notebook) => (
                        <SelectItem key={notebook.id} value={notebook.id}>
                          {notebook.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          )}

          {selectedFile && (
            <div className="flex items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs">
              <div className="flex min-w-0 items-center gap-2">
                {selectedFileKind === 'audio' ? (
                  <AudioLines className="h-4 w-4 flex-shrink-0" />
                ) : selectedFileKind === 'video' ? (
                  <Video className="h-4 w-4 flex-shrink-0" />
                ) : (
                  <ImageIcon className="h-4 w-4 flex-shrink-0" />
                )}
                <span className="truncate">{selectedFile.name}</span>
                <span className="flex-shrink-0 text-muted-foreground">
                  {formatFileSize(selectedFile.size)}
                </span>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 flex-shrink-0"
                onClick={() => {
                  setSelectedFile(null)
                  if (fileInputRef.current) {
                    fileInputRef.current.value = ''
                  }
                }}
                disabled={isStreaming}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}

          <div className="flex gap-2 items-end min-w-0">
            {enableAttachments && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/jpg,image/webp,video/mp4,video/webm,video/quicktime,video/x-msvideo,audio/wav,audio/mpeg,audio/mp3,audio/mp4,audio/x-m4a,audio/flac,audio/ogg,audio/aac,audio/webm,text/csv,text/tab-separated-values,application/json,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.csv,.tsv,.json,.xls,.xlsx"
                  className="hidden"
                  onChange={handleFileChange}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="h-[40px] w-[40px] flex-shrink-0"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isStreaming}
                >
                  <Paperclip className="h-4 w-4" />
                </Button>
              </>
            )}
            <Textarea
              id={chatInputId}
              name="chat-message"
              autoComplete="off"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`${t.chat.sendPlaceholder} (${t.chat.pressToSend.replace('{key}', keyHint)})`}
              disabled={isStreaming}
              className="flex-1 min-h-[40px] max-h-[100px] resize-none py-2 px-3 min-w-0"
              rows={1}
            />
            <Button
              onClick={handleSend}
              disabled={(!input.trim() && !selectedFile) || isStreaming}
              size="icon"
              className="h-[40px] w-[40px] flex-shrink-0"
            >
              {isStreaming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </CardContent>
      )}
    </Card>

    </>
  )
}

function extractChartArtifacts(content: string): {
  imageSrc?: string
  tableMarkdown?: string
} {
  const imageMatch = content.match(/!\[(?:Gráfico gerado|Grafico gerado|Generated chart)\]\(([^)]+)\)/i)
  const detailsMatch = content.match(/<details>\s*<summary>[^<]*<\/summary>\s*([\s\S]*?)\s*<\/details>/i)
  const tableMarkdown = detailsMatch?.[1]?.trim()

  return {
    imageSrc: imageMatch?.[1]?.trim(),
    tableMarkdown: tableMarkdown && tableMarkdown.includes('|') ? tableMarkdown : undefined,
  }
}

function markdownTableToCsv(markdown: string): string {
  const rows = markdown
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.startsWith('|') && line.endsWith('|'))
    .map((line) => line.slice(1, -1).split('|').map((cell) => cell.trim()))
    .filter((cells) => !cells.every((cell) => /^:?-{3,}:?$/.test(cell)))

  return rows
    .map((cells) =>
      cells
        .map((cell) => `"${cell.replaceAll('"', '""')}"`)
        .join(',')
    )
    .join('\n')
}

function downloadText(content: string, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

async function copyImageToClipboard(src: string): Promise<void> {
  if (!navigator.clipboard) {
    throw new Error('Clipboard unavailable')
  }

  if ('ClipboardItem' in window && navigator.clipboard.write) {
    const response = await fetch(src)
    const blob = await response.blob()
    await navigator.clipboard.write([
      new ClipboardItem({ [blob.type || 'image/png']: blob }),
    ])
    return
  }

  await navigator.clipboard.writeText(src)
}

function downloadImage(src: string): void {
  const anchor = document.createElement('a')
  anchor.href = src
  anchor.download = 'chart.png'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

function ChartArtifactActions({ content }: { content: string }) {
  const { t } = useTranslation()
  const { imageSrc, tableMarkdown } = extractChartArtifacts(content)
  if (!imageSrc && !tableMarkdown) return null

  const tableCsv = tableMarkdown ? markdownTableToCsv(tableMarkdown) : ''

  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {imageSrc && (
        <>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 gap-1.5"
            title="Copiar gráfico"
            aria-label="Copiar gráfico"
            onClick={async () => {
              try {
                await copyImageToClipboard(imageSrc)
                toast.success(t.common.copyToClipboard)
              } catch {
                toast.error(t.common.error)
              }
            }}
          >
            <Copy className="h-3.5 w-3.5" />
            Copiar gráfico
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 gap-1.5"
            title="Transferir gráfico"
            aria-label="Transferir gráfico"
            onClick={() => downloadImage(imageSrc)}
          >
            <Download className="h-3.5 w-3.5" />
            Transferir gráfico
          </Button>
        </>
      )}
      {tableMarkdown && (
        <>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 gap-1.5"
            title="Copiar tabela"
            aria-label="Copiar tabela"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(tableCsv || tableMarkdown)
                toast.success(t.common.copyToClipboard)
              } catch {
                toast.error(t.common.error)
              }
            }}
          >
            <Table2 className="h-3.5 w-3.5" />
            Copiar tabela
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 gap-1.5"
            title="Transferir tabela"
            aria-label="Transferir tabela"
            onClick={() => downloadText(tableCsv || tableMarkdown, 'chart-data.csv', 'text/csv;charset=utf-8')}
          >
            <Download className="h-3.5 w-3.5" />
            Transferir tabela
          </Button>
        </>
      )}
    </div>
  )
}

// Helper component to render AI messages with clickable references
function AIMessageContent({
  content,
  onReferenceClick,
  onMediaLoad,
}: {
  content: string
  onReferenceClick: (type: string, id: string) => void
  onMediaLoad?: () => void
}) {
  const { t } = useTranslation()
  // Convert references to compact markdown with numbered citations
  const markdownWithCompactRefs = convertReferencesToCompactMarkdown(content, t.common.references)

  // Create custom link component for compact references
  const ReferenceLinkComponent = createCompactReferenceLinkComponent(onReferenceClick)
  const LinkComponent = ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href?: string
    children?: React.ReactNode
  }) => {
    const isVideoAsset =
      !!href && (href.startsWith('data:video/') || /\/api\/vision\/note-asset\/[^)\s]+\.(mp4|webm|mov)$/i.test(href))

    if (isVideoAsset) {
      return (
        <video
          src={href}
          controls
          className="my-3 max-h-80 w-full rounded-md border bg-black"
        >
          {children}
        </video>
      )
    }

    return <ReferenceLinkComponent href={href} {...props}>{children}</ReferenceLinkComponent>
  }

  return (
    <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none break-words prose-headings:font-semibold prose-a:text-blue-600 prose-a:break-all prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-p:mb-4 prose-p:leading-7 prose-li:mb-2">
      <ChartArtifactActions content={content} />
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: LinkComponent,
          img: ({ src, alt }) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={typeof src === 'string' ? src : undefined}
              alt={alt ?? ''}
              className="my-3 max-h-80 rounded-md border object-contain"
              onLoad={onMediaLoad}
            />
          ),
          p: ({ children }) => <p className="mb-4">{children}</p>,
          h1: ({ children }) => <h1 className="mb-4 mt-6">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-5">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-3 mt-4">{children}</h3>,
          h4: ({ children }) => <h4 className="mb-2 mt-4">{children}</h4>,
          h5: ({ children }) => <h5 className="mb-2 mt-3">{children}</h5>,
          h6: ({ children }) => <h6 className="mb-2 mt-3">{children}</h6>,
          li: ({ children }) => <li className="mb-1">{children}</li>,
          ul: ({ children }) => <ul className="mb-4 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="mb-4 space-y-1">{children}</ol>,
          table: ({ children }) => (
            <div className="my-4 overflow-x-auto">
              <table className="min-w-full border-collapse border border-border">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b border-border">{children}</tr>,
          th: ({ children }) => <th className="border border-border px-3 py-2 text-left font-semibold">{children}</th>,
          td: ({ children }) => <td className="border border-border px-3 py-2">{children}</td>,
        }}
      >
        {markdownWithCompactRefs}
      </ReactMarkdown>
    </div>
  )
}
