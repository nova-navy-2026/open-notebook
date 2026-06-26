'use client'

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { sourcesApi } from '@/lib/api/sources'
import { SourceListResponse } from '@/lib/types/api'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { EmptyState } from '@/components/common/EmptyState'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { FileText, Link as LinkIcon, Upload, AlignLeft, Trash2, ArrowUpDown, Search, LayoutGrid, List as ListIcon, Sparkles, Loader2, Plus } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useCreateDialogs } from '@/lib/hooks/use-create-dialogs'
import { getDateLocale } from '@/lib/utils/date-locale'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { useNavyDocuments } from '@/lib/hooks/use-navy-docs'
import { NavyDocsSection } from '@/components/notebooks/NavyDocsSection'
import { PageInfoButton } from '@/components/common/PageInfoButton'

type SourceTypeKey = 'link' | 'file' | 'text'
type SourceStatusKey = 'ready' | 'processing' | 'not_embedded'

export default function SourcesPage() {
  const { t, language } = useTranslation()
  const { openSourceDialog } = useCreateDialogs()
  const [sources, setSources] = useState<SourceListResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [sortBy, setSortBy] = useState<'created' | 'updated'>('updated')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list')
  const [searchTerm, setSearchTerm] = useState('')
  const [typeFilter, setTypeFilter] = useState<'all' | SourceTypeKey>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | SourceStatusKey>('all')
  const [deleteDialog, setDeleteDialog] = useState<{ open: boolean; source: SourceListResponse | null }>({
    open: false,
    source: null
  })
  const router = useRouter()
  const tableRef = useRef<HTMLTableElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const offsetRef = useRef(0)
  const loadingMoreRef = useRef(false)
  const hasMoreRef = useRef(true)
  const PAGE_SIZE = 30

  const getSourceTypeKey = (source: SourceListResponse): SourceTypeKey => {
    if (source.asset?.url) return 'link'
    if (source.asset?.file_path) return 'file'
    return 'text'
  }

  const getSourceStatusKey = (source: SourceListResponse): SourceStatusKey => {
    const status = (source.status || '').toLowerCase()
    if (status && status !== 'completed' && status !== 'done' && status !== 'ready' && status !== 'success') {
      return 'processing'
    }
    if (!source.embedded) return 'not_embedded'
    return 'ready'
  }

  const filteredSources = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    return sources.filter((source) => {
      if (typeFilter !== 'all' && getSourceTypeKey(source) !== typeFilter) return false
      if (statusFilter !== 'all' && getSourceStatusKey(source) !== statusFilter) return false
      if (term) {
        const haystack = `${source.title ?? ''} ${source.asset?.url ?? ''}`.toLowerCase()
        if (!haystack.includes(term)) return false
      }
      return true
    })
  }, [sources, searchTerm, typeFilter, statusFilter])


  // Navy corpus docs (read-only catalog on this page)
  const { data: navyData } = useNavyDocuments()
  const hasNavyDocs = (navyData?.documents?.length ?? 0) > 0

  const fetchSources = useCallback(async (reset = false) => {
    try {
      // Check flags before proceeding
      if (!reset && (loadingMoreRef.current || !hasMoreRef.current)) {
        return
      }

      if (reset) {
        setLoading(true)
        offsetRef.current = 0
        setSources([])
        hasMoreRef.current = true
      } else {
        loadingMoreRef.current = true
        setLoadingMore(true)
      }

      const data = await sourcesApi.list({
        limit: PAGE_SIZE,
        offset: offsetRef.current,
        sort_by: sortBy,
        sort_order: sortOrder,
      })

      if (reset) {
        setSources(data)
      } else {
        setSources(prev => [...prev, ...data])
      }

      // Check if we have more data
      const hasMoreData = data.length === PAGE_SIZE
      hasMoreRef.current = hasMoreData
      offsetRef.current += data.length
    } catch (err) {
      console.error('Failed to fetch sources:', err)
      setError(t.sources.failedToLoad)
      toast.error(t.sources.failedToLoad)
    } finally {
      setLoading(false)
      setLoadingMore(false)
      loadingMoreRef.current = false
    }
  }, [sortBy, sortOrder, t.sources.failedToLoad])

  // Initial load and when sort changes
  useEffect(() => {
    fetchSources(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortBy, sortOrder])

  useEffect(() => {
    // Focus the table when component mounts or sources change
    if (sources.length > 0 && tableRef.current) {
      tableRef.current.focus()
    }
  }, [sources])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (filteredSources.length === 0) return

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          setSelectedIndex((prev) => {
            const newIndex = Math.min(prev + 1, filteredSources.length - 1)
            // Scroll to keep selected row visible
            setTimeout(() => scrollToSelectedRow(newIndex), 0)
            return newIndex
          })
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex((prev) => {
            const newIndex = Math.max(prev - 1, 0)
            // Scroll to keep selected row visible
            setTimeout(() => scrollToSelectedRow(newIndex), 0)
            return newIndex
          })
          break
        case 'Enter':
          e.preventDefault()
          if (filteredSources[selectedIndex]) {
            router.push(`/sources/${filteredSources[selectedIndex].id}`)
          }
          break
        case 'Home':
          e.preventDefault()
          setSelectedIndex(0)
          setTimeout(() => scrollToSelectedRow(0), 0)
          break
        case 'End':
          e.preventDefault()
          const lastIndex = filteredSources.length - 1
          setSelectedIndex(lastIndex)
          setTimeout(() => scrollToSelectedRow(lastIndex), 0)
          break
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [filteredSources, selectedIndex, router])

  const scrollToSelectedRow = (index: number) => {
    const scrollContainer = scrollContainerRef.current
    if (!scrollContainer) return

    // Find the selected row element
    const rows = scrollContainer.querySelectorAll('tbody tr')
    const selectedRow = rows[index] as HTMLElement
    if (!selectedRow) return

    const containerRect = scrollContainer.getBoundingClientRect()
    const rowRect = selectedRow.getBoundingClientRect()

    // Check if row is above visible area
    if (rowRect.top < containerRect.top) {
      selectedRow.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    // Check if row is below visible area
    else if (rowRect.bottom > containerRect.bottom) {
      selectedRow.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }

  // Set up scroll listener after sources are loaded
  useEffect(() => {
    const scrollContainer = scrollContainerRef.current
    if (!scrollContainer) return

    let scrollTimeout: NodeJS.Timeout | null = null

    const handleScroll = () => {
      if (scrollTimeout) {
        clearTimeout(scrollTimeout)
      }

      scrollTimeout = setTimeout(() => {
        if (!scrollContainerRef.current) return

        const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current
        const distanceFromBottom = scrollHeight - scrollTop - clientHeight

        // Load more when within 200px of the bottom
        if (distanceFromBottom < 200 && !loadingMoreRef.current && hasMoreRef.current) {
          fetchSources(false)
        }
      }, 100)
    }

    scrollContainer.addEventListener('scroll', handleScroll)
    handleScroll() // Check on mount

    return () => {
      scrollContainer.removeEventListener('scroll', handleScroll)
      if (scrollTimeout) {
        clearTimeout(scrollTimeout)
      }
    }
  }, [fetchSources, sources.length, viewMode])

  const toggleSort = (field: 'created' | 'updated') => {
    if (sortBy === field) {
      // Toggle order if clicking the same field
      setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc')
    } else {
      // Switch to new field with default desc order
      setSortBy(field)
      setSortOrder('desc')
    }
  }

  const getSourceIcon = (source: SourceListResponse) => {
    if (source.asset?.url) return <LinkIcon className="h-4 w-4" />
    if (source.asset?.file_path) return <Upload className="h-4 w-4" />
    return <AlignLeft className="h-4 w-4" />
  }

  const getSourceType = (source: SourceListResponse) => {
    if (source.asset?.url) return t.sources.type.link
    if (source.asset?.file_path) return t.sources.type.file
    return t.sources.type.text
  }

  const handleRowClick = useCallback((index: number, sourceId: string) => {
    setSelectedIndex(index)
    router.push(`/sources/${sourceId}`)
  }, [router])

  const handleDeleteClick = useCallback((e: React.MouseEvent, source: SourceListResponse) => {
    e.stopPropagation() // Prevent row click
    setDeleteDialog({ open: true, source })
  }, [])

  const handleDeleteConfirm = async () => {
    if (!deleteDialog.source) return

    try {
      await sourcesApi.delete(deleteDialog.source.id)
      toast.success(t.sources.deleteSuccess)
      // Remove the deleted source from the list
      setSources(prev => prev.filter(s => s.id !== deleteDialog.source?.id))
      setDeleteDialog({ open: false, source: null })
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      console.error('Failed to delete source:', error)
      toast.error(t(getApiErrorKey(error.response?.data?.detail || error.message)))
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-red-500">{error}</p>
      </div>
    )
  }

  if (sources.length === 0 && !hasNavyDocs) {
    return (
      <EmptyState
        icon={FileText}
        title={t.sources.noSourcesYet}
        description={t.sources.allSourcesDescShort}
      />
    )
  }

  return (
    <>
      <div className="app-page-wide flex h-full flex-col">
        <div className="mb-4 flex flex-shrink-0 items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-bold">{t.sources.allSources}</h1>
            <PageInfoButton pageKey="sources" />
          </div>
          <Button onClick={() => openSourceDialog()} className="flex-shrink-0">
            <Plus className="mr-2 h-4 w-4" />
            {t.common.newSource ?? 'New Source'}
          </Button>
        </div>

        {/* Knowledge Base (OpenSearch corpus) — shown on top. */}
        {hasNavyDocs && (
          <div className="mb-4 flex-shrink-0">
            <NavyDocsSection readOnly />
          </div>
        )}

        {/* Uploaded sources — always visible (even when empty), beneath the
            OpenSearch / Knowledge Base sources. */}
        <div className="mb-2 flex-shrink-0">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              {t.sources.uploadedSources}
            </h2>
            {sources.length > 0 && (
              <Badge variant="secondary" className="text-xs">
                {sources.length}
              </Badge>
            )}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t.sources.uploadedSourcesDesc}
          </p>
        </div>

        {sources.length === 0 && (
          <div className="flex-shrink-0 rounded-md border border-dashed px-4 py-6 text-center">
            <FileText className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
            <p className="text-sm font-medium">{t.sources.noUploadedSourcesYet}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t.sources.uploadedSourcesEmptyDesc}
            </p>
          </div>
        )}

        {sources.length > 0 && (
          <div className="mb-3 flex flex-shrink-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-1 flex-wrap items-center gap-2">
                <div className="relative w-full sm:max-w-xs">
                  <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder={t.sources.searchSources}
                    className="pl-8"
                    aria-label={t.sources.searchSources}
                  />
                </div>
                <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v as 'all' | SourceTypeKey)}>
                  <SelectTrigger className="w-auto min-w-[150px]">
                    <SelectValue placeholder={t.sources.filterByType} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t.sources.allTypes}</SelectItem>
                    <SelectItem value="link">{t.sources.type.link}</SelectItem>
                    <SelectItem value="file">{t.sources.type.file}</SelectItem>
                    <SelectItem value="text">{t.sources.type.text}</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as 'all' | SourceStatusKey)}>
                  <SelectTrigger className="w-auto min-w-[170px]">
                    <SelectValue placeholder={t.sources.filterByStatus} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t.sources.allStatuses}</SelectItem>
                    <SelectItem value="ready">{t.sources.filterReady}</SelectItem>
                    <SelectItem value="processing">{t.sources.filterProcessing}</SelectItem>
                    <SelectItem value="not_embedded">{t.sources.filterNotEmbedded}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  {t.sources.showingCount
                    .replace('{count}', String(filteredSources.length))
                    .replace('{total}', String(sources.length))}
                </span>
                <div className="flex items-center rounded-md border">
                  <Button
                    variant={viewMode === 'list' ? 'secondary' : 'ghost'}
                    size="icon"
                    className="h-8 w-8 rounded-r-none"
                    onClick={() => setViewMode('list')}
                    aria-label={t.sources.listView}
                    title={t.sources.listView}
                  >
                    <ListIcon className="h-4 w-4" />
                  </Button>
                  <Button
                    variant={viewMode === 'grid' ? 'secondary' : 'ghost'}
                    size="icon"
                    className="h-8 w-8 rounded-l-none"
                    onClick={() => setViewMode('grid')}
                    aria-label={t.sources.gridView}
                    title={t.sources.gridView}
                  >
                    <LayoutGrid className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}

        {sources.length > 0 && filteredSources.length === 0 && (
          <div className="flex flex-1 items-center justify-center rounded-md border text-sm text-muted-foreground">
            {t.sources.noMatchingSources}
          </div>
        )}

        {sources.length > 0 && filteredSources.length > 0 && viewMode === 'grid' && (
          <div ref={scrollContainerRef} className="flex-1 overflow-auto rounded-md">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filteredSources.map((source, index) => {
                const statusKey = getSourceStatusKey(source)
                return (
                  <Card
                    key={source.id}
                    onClick={() => handleRowClick(index, source.id)}
                    onMouseEnter={() => setSelectedIndex(index)}
                    className={cn(
                      'group flex cursor-pointer flex-col gap-3 p-4 transition-colors',
                      // Highlight only on hover (a border stays inside the card,
                      // so it never pokes out of the scroll container the way a
                      // persistent ring did).
                      'hover:border-primary hover:bg-muted/50',
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        {getSourceIcon(source)}
                        <Badge variant="secondary" className="text-xs">
                          {getSourceType(source)}
                        </Badge>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => handleDeleteClick(e, source)}
                        className="h-7 w-7 text-destructive opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    <div className="min-h-[2.5rem]">
                      <p className="line-clamp-2 font-medium" title={source.title || t.sources.untitledSource}>
                        {source.title || t.sources.untitledSource}
                      </p>
                      {source.asset?.url && (
                        <p className="mt-0.5 truncate text-xs text-muted-foreground" title={source.asset.url}>
                          {source.asset.url}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge
                        variant={statusKey === 'ready' ? 'default' : 'secondary'}
                        className="gap-1 text-xs"
                      >
                        {statusKey === 'processing' && <Loader2 className="h-3 w-3 animate-spin" />}
                        {statusKey === 'ready'
                          ? t.sources.filterReady
                          : statusKey === 'processing'
                            ? t.sources.filterProcessing
                            : t.sources.filterNotEmbedded}
                      </Badge>
                      {(source.insights_count || 0) > 0 && (
                        <Badge variant="outline" className="gap-1 text-xs">
                          <Sparkles className="h-3 w-3" />
                          {source.insights_count}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-auto text-xs text-muted-foreground">
                      {formatDistanceToNow(new Date(source.created), {
                        addSuffix: true,
                        locale: getDateLocale(language),
                      })}
                    </p>
                  </Card>
                )
              })}
            </div>
            {loadingMore && (
              <div className="flex items-center justify-center py-6">
                <LoadingSpinner />
                <span className="ml-2 text-muted-foreground">{t.sources.loadingMore}</span>
              </div>
            )}
          </div>
        )}

        {sources.length > 0 && filteredSources.length > 0 && viewMode === 'list' && (
        <div ref={scrollContainerRef} className="flex-1 rounded-md border overflow-auto">
          <table
            ref={tableRef}
            tabIndex={0}
            className="w-full min-w-[800px] outline-none table-fixed"
          >
            <colgroup>
              <col className="w-[120px]" />
              <col className="w-auto" />
              <col className="w-[140px]" />
              <col className="w-[100px]" />
              <col className="w-[100px]" />
              <col className="w-[100px]" />
            </colgroup>
            <thead className="sticky top-0 bg-background z-10">
              <tr className="border-b bg-muted/50">
                <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">
                  {t.common.type}
                </th>
                <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">
                  {t.common.title}
                </th>
                <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground hidden sm:table-cell">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => toggleSort('created')}
                    className="h-8 px-2 hover:bg-muted"
                  >
                    {t.common.created_label}
                    <ArrowUpDown className={cn(
                      "ml-2 h-3 w-3",
                      sortBy === 'created' ? 'opacity-100' : 'opacity-30'
                    )} />
                    {sortBy === 'created' && (
                      <span className="ml-1 text-xs">
                        {sortOrder === 'asc' ? '↑' : '↓'}
                      </span>
                    )}
                  </Button>
                </th>
                <th className="h-12 px-4 text-center align-middle font-medium text-muted-foreground hidden md:table-cell">
                  {t.sources.insights}
                </th>
                <th className="h-12 px-4 text-center align-middle font-medium text-muted-foreground hidden lg:table-cell">
                  {t.sources.embedded}
                </th>
                <th className="h-12 px-4 text-right align-middle font-medium text-muted-foreground">
                  {t.common.actions}
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredSources.map((source, index) => (
                <tr
                  key={source.id}
                  onClick={() => handleRowClick(index, source.id)}
                  onMouseEnter={() => setSelectedIndex(index)}
                  className={cn(
                    "border-b transition-colors cursor-pointer",
                    selectedIndex === index
                      ? "bg-accent"
                      : "hover:bg-muted/50"
                  )}
                >
                  <td className="h-12 px-4">
                    <div className="flex items-center gap-2">
                      {getSourceIcon(source)}
                      <Badge variant="secondary" className="text-xs">
                        {getSourceType(source)}
                      </Badge>
                    </div>
                  </td>
                  <td className="h-12 px-4">
                    <div className="flex flex-col overflow-hidden">
                      <span className="font-medium truncate">
                        {source.title || t.sources.untitledSource}
                      </span>
                      {source.asset?.url && (
                        <span className="text-xs text-muted-foreground truncate">
                          {source.asset.url}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="h-12 px-4 text-muted-foreground text-sm hidden sm:table-cell">
                    {formatDistanceToNow(new Date(source.created), { 
                      addSuffix: true,
                      locale: getDateLocale(language)
                    })}
                  </td>
                  <td className="h-12 px-4 text-center hidden md:table-cell">
                    <span className="text-sm font-medium">{source.insights_count || 0}</span>
                  </td>
                  <td className="h-12 px-4 text-center hidden lg:table-cell">
                    <Badge variant={source.embedded ? "default" : "secondary"} className="text-xs">
                      {source.embedded ? t.sources.yes : t.sources.no}
                    </Badge>
                  </td>
                  <td className="h-12 px-4 text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={(e) => handleDeleteClick(e, source)}
                      className="text-destructive hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
              {loadingMore && (
                <tr>
                  <td colSpan={6} className="h-16 text-center">
                    <div className="flex items-center justify-center">
                      <LoadingSpinner />
                      <span className="ml-2 text-muted-foreground">{t.sources.loadingMore}</span>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        )}

      </div>

      <ConfirmDialog
        open={deleteDialog.open}
        onOpenChange={(open) => setDeleteDialog({ open, source: deleteDialog.source })}
        title={t.sources.delete}
        description={t.sources.deleteConfirmWithTitle.replace('{title}', deleteDialog.source?.title || t.sources.untitledSource)}
        confirmText={t.common.delete}
        confirmVariant="destructive"
        onConfirm={handleDeleteConfirm}
      />
    </>
  )
}
