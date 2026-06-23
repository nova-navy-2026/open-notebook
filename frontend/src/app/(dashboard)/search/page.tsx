"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslation } from "@/lib/hooks/use-translation";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Search,
  ChevronDown,
  X,
  FileText,
  FileSearch,
  StickyNote,
  Lightbulb,
  FileBox,
} from "lucide-react";
import { useSearch } from "@/lib/hooks/use-search";
import { useSettings } from "@/lib/hooks/use-settings";
import { useModelDefaults } from "@/lib/hooks/use-models";
import { useModalManager } from "@/lib/hooks/use-modal-manager";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { PageInfoButton } from "@/components/common/PageInfoButton";
import { VoiceInputButton } from "@/components/common/VoiceInputButton";

const RECENT_SEARCHES_KEY = "open-notebook:recent-searches";
const MAX_RECENT = 8;

export default function SearchPage() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const urlQuery = searchParams?.get("q") || "";

  // Search state
  const [searchQuery, setSearchQuery] = useState(urlQuery);
  const [searchSources, setSearchSources] = useState(true);
  const [searchNotes, setSearchNotes] = useState(true);
  const [groupByType, setGroupByType] = useState(false);
  const [typeOverride, setTypeOverride] = useState<"text" | "vector" | "hybrid" | null>(null);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);

  // Hooks
  const searchMutation = useSearch();
  const { data: settings } = useSettings();
  const { data: modelDefaults } = useModelDefaults();
  const { openModal } = useModalManager();

  const hasEmbeddingModel = !!modelDefaults?.default_embedding_model;

  // Determine default search type from admin settings, falling back to hybrid or text
  const defaultSearchType: "text" | "vector" | "hybrid" = (() => {
    const configured = settings?.default_search_type as
      | "text"
      | "vector"
      | "hybrid"
      | undefined;
    if (configured === "vector" || configured === "hybrid") {
      return hasEmbeddingModel ? configured : "text";
    }
    return configured || (hasEmbeddingModel ? "hybrid" : "text");
  })();

  // Effective search type: user override (if valid) otherwise admin default
  const searchType: "text" | "vector" | "hybrid" =
    typeOverride && (typeOverride === "text" || hasEmbeddingModel)
      ? typeOverride
      : defaultSearchType;

  const hasAutoTriggeredRef = useRef(false);

  // Load recent searches from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem(RECENT_SEARCHES_KEY);
      if (stored) setRecentSearches(JSON.parse(stored));
    } catch {
      // ignore malformed storage
    }
  }, []);

  const pushRecentSearch = useCallback((query: string) => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setRecentSearches((prev) => {
      const next = [trimmed, ...prev.filter((q) => q !== trimmed)].slice(0, MAX_RECENT);
      try {
        localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(next));
      } catch {
        // ignore storage errors
      }
      return next;
    });
  }, []);

  const clearRecentSearches = useCallback(() => {
    setRecentSearches([]);
    try {
      localStorage.removeItem(RECENT_SEARCHES_KEY);
    } catch {
      // ignore
    }
  }, []);

  const runSearch = useCallback(
    (query: string) => {
      if (!query.trim()) return;
      pushRecentSearch(query);
      searchMutation.mutate({
        query,
        type: searchType,
        limit: 10,
        search_sources: searchSources,
        search_notes: searchNotes,
        minimum_score: 0.2,
      });
    },
    [searchType, searchSources, searchNotes, searchMutation, pushRecentSearch],
  );

  const handleSearch = useCallback(() => {
    runSearch(searchQuery);
  }, [runSearch, searchQuery]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSearch();
    }
  };

  // Dictated speech just fills the search bar; the user reviews it and runs the
  // search themselves (same flow as the chat prompt box).
  const handleVoiceTranscript = useCallback((text: string) => {
    const query = text.trim();
    if (!query) return;
    setSearchQuery(query);
  }, []);

  // Auto-trigger search from URL params
  useEffect(() => {
    if (hasAutoTriggeredRef.current || !urlQuery) return;
    handleSearch();
    hasAutoTriggeredRef.current = true;
  }, [urlQuery, handleSearch]);

  // Group results by parent type for the optional grouped view
  const groupedResults = useMemo(() => {
    const results = searchMutation.data?.results ?? [];
    const groups = new Map<string, typeof results>();
    for (const result of results) {
      const type = (result.parent_id?.split(":")[0] as string) || "other";
      const existing = groups.get(type) ?? [];
      existing.push(result);
      groups.set(type, existing);
    }
    return Array.from(groups.entries());
  }, [searchMutation.data]);

  const typeMeta = (type: string, isNavy: boolean) => {
    if (isNavy)
      return { label: "Document", Icon: FileBox, color: "text-sky-600 dark:text-sky-400" };
    switch (type) {
      case "source":
        return { label: "Source", Icon: FileText, color: "text-violet-600 dark:text-violet-400" };
      case "note":
        return { label: "Note", Icon: StickyNote, color: "text-amber-600 dark:text-amber-400" };
      default:
        return { label: "Insight", Icon: Lightbulb, color: "text-emerald-600 dark:text-emerald-400" };
    }
  };

  const renderResult = (result: (typeof groupedResults)[number][1][number], key: string | number) => {
    if (!result.parent_id) {
      console.warn("Search result with null parent_id:", result);
      return null;
    }
    const [type, id] = result.parent_id.split(":");
    const isNavy = type === "navy";
    const modalType = isNavy
      ? null
      : type === "source_insight"
        ? "insight"
        : (type as "source" | "note" | "insight");
    const { label: typeLabel, Icon, color } = typeMeta(type, isNavy);
    const matchCount = result.matches?.length ?? 0;
    const preview = result.matches?.[0];

    return (
      <Card
        key={key}
        className="group overflow-hidden border-border/60 transition-all hover:border-primary/40 hover:shadow-sm"
      >
        <CardContent className="flex gap-3 p-4">
          <div
            className={`mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-muted ${color}`}
          >
            <Icon className="h-4 w-4" />
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3">
              {modalType ? (
                <button
                  onClick={() => openModal(modalType, id)}
                  className="truncate text-left font-medium text-foreground hover:text-primary hover:underline"
                  title={result.title}
                >
                  {result.title}
                </button>
              ) : (
                <span
                  className="truncate font-medium text-foreground"
                  title={result.title}
                >
                  {result.title}
                </span>
              )}
              <span className="flex-shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium tabular-nums text-primary">
                {result.final_score.toFixed(2)}
              </span>
            </div>

            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className="text-[10px] font-normal">
                {typeLabel}
              </Badge>
              {matchCount > 1 && (
                <Badge variant="secondary" className="text-[10px] font-normal">
                  {matchCount} chunks
                </Badge>
              )}
            </div>

            {preview && (
              <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
                {preview}
              </p>
            )}

            {result.matches && result.matches.length > 1 && (
              <Collapsible className="mt-2">
                <CollapsibleTrigger className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground [&[data-state=open]>svg]:rotate-180">
                  <ChevronDown className="h-3.5 w-3.5 transition-transform" />
                  {t.searchPage.matches.replace(
                    "{count}",
                    result.matches.length.toString(),
                  )}
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-2 space-y-1.5">
                  {result.matches.map((match, i) => (
                    <div
                      key={i}
                      className="rounded-md border-l-2 border-primary/30 bg-muted/40 py-1.5 pl-3 pr-2 text-sm text-muted-foreground"
                    >
                      {match}
                    </div>
                  ))}
                </CollapsibleContent>
              </Collapsible>
            )}
          </div>
        </CardContent>
      </Card>
    );
  };

  const groupLabel = (type: string) =>
    type === "navy"
      ? "Documents"
      : type === "source"
        ? "Sources"
        : type === "note"
          ? "Notes"
          : type === "source_insight"
            ? "Insights"
            : "Other";

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="app-page space-y-6">
      <div className="flex items-center gap-2 mb-4 md:mb-6">
        <h1 className="text-xl md:text-2xl font-bold">
          {t.searchPage.search}
        </h1>
        <PageInfoButton pageKey="search" />
      </div>

      <Card className="app-section">
        <CardHeader>
          <CardTitle className="text-lg">{t.searchPage.search}</CardTitle>
          <p className="text-sm text-muted-foreground">
            {t.searchPage.searchDesc}
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Search Input */}
          <div className="space-y-2">
            <Label htmlFor="search-query" className="sr-only">
              {t.searchPage.search}
            </Label>
            <div className="app-control-row flex flex-col sm:flex-row gap-2">
              <Input
                id="search-query"
                name="search-query"
                placeholder={t.searchPage.enterSearchPlaceholder}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyPress={handleKeyPress}
                disabled={searchMutation.isPending}
                className="flex-1"
                aria-label={t.common.accessibility.enterSearch}
                autoComplete="off"
              />
              <VoiceInputButton
                onTranscript={handleVoiceTranscript}
                disabled={searchMutation.isPending}
                className="w-full sm:w-auto"
              />
              <Button
                onClick={handleSearch}
                disabled={searchMutation.isPending || !searchQuery.trim()}
                aria-label={t.common.accessibility.searchKBBtn}
                className="w-full sm:w-auto"
              >
                {searchMutation.isPending ? (
                  <LoadingSpinner size="sm" />
                ) : (
                  <Search className="h-4 w-4 mr-2" />
                )}
                {t.searchPage.search}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {t.searchPage.pressToSearch}
            </p>

            {/* Recent searches */}
            {recentSearches.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <span className="text-xs text-muted-foreground mr-1">
                  {t.searchPage.recentSearches}:
                </span>
                {recentSearches.map((query) => (
                  <button
                    key={query}
                    type="button"
                    onClick={() => {
                      setSearchQuery(query);
                      runSearch(query);
                    }}
                    className="rounded-full border bg-muted/40 px-2.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    {query}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={clearRecentSearches}
                  className="ml-1 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive"
                >
                  <X className="h-3 w-3" />
                  {t.searchPage.clearRecent}
                </button>
              </div>
            )}
          </div>

          {/* Search Options */}
          <div className="space-y-4">
            {/* Search type selector */}
            <div className="space-y-2">
              <span className="text-sm font-medium leading-none">
                {t.searchPage.searchType}
              </span>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {([
                  { value: "text", label: t.searchPage.textSearch, desc: t.searchPage.searchTypeDescText, disabled: false },
                  { value: "vector", label: t.searchPage.vectorSearch, desc: t.searchPage.searchTypeDescVector, disabled: !hasEmbeddingModel },
                  { value: "hybrid", label: t.searchPage.hybridSearch, desc: t.searchPage.searchTypeDescHybrid, disabled: !hasEmbeddingModel },
                ] as const).map((option) => {
                  const active = searchType === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      disabled={option.disabled || searchMutation.isPending}
                      onClick={() => setTypeOverride(option.value)}
                      className={`flex flex-col items-start gap-0.5 rounded-md border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                        active ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted/50"
                      }`}
                    >
                      <span className="text-sm font-medium">{option.label}</span>
                      <span className="text-xs text-muted-foreground">{option.desc}</span>
                    </button>
                  );
                })}
              </div>
              {!hasEmbeddingModel && (
                <p className="text-xs text-muted-foreground">
                  {t.searchPage.vectorSearchWarning}
                </p>
              )}
            </div>

            {/* Search Locations */}
            <div
              className="space-y-2"
              role="group"
              aria-labelledby="search-in-label"
            >
              <span
                id="search-in-label"
                className="text-sm font-medium leading-none"
              >
                {t.searchPage.searchIn}
              </span>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {([
                  {
                    key: "sources" as const,
                    label: t.searchPage.searchSources,
                    desc: t.searchPage.searchSourcesDesc,
                    active: searchSources,
                    toggle: () => setSearchSources(!searchSources),
                  },
                  {
                    key: "notes" as const,
                    label: t.searchPage.searchNotes,
                    desc: t.searchPage.searchNotesDesc,
                    active: searchNotes,
                    toggle: () => setSearchNotes(!searchNotes),
                  },
                ]).map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    aria-pressed={option.active}
                    disabled={searchMutation.isPending}
                    onClick={option.toggle}
                    className={`flex flex-col items-start gap-0.5 rounded-md border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                      option.active
                        ? "border-primary bg-primary/5 ring-1 ring-primary"
                        : "hover:bg-muted/50"
                    }`}
                  >
                    <span className="text-sm font-medium">{option.label}</span>
                    <span className="text-xs text-muted-foreground">
                      {option.desc}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Loading state */}
          {searchMutation.isPending && (
            <div className="mt-6 flex flex-col items-center justify-center gap-2 py-10 text-muted-foreground">
              <LoadingSpinner />
              <span className="text-sm">{t.searchPage.searching}</span>
            </div>
          )}

          {/* Initial / empty prompt */}
          {!searchMutation.isPending && !searchMutation.data && (
            <div className="mt-6 flex flex-col items-center justify-center gap-2 py-10 text-center text-muted-foreground">
              <FileSearch className="h-10 w-10 opacity-40" />
              <p className="text-sm font-medium">{t.searchPage.startSearchingTitle}</p>
              <p className="text-xs">{t.searchPage.startSearchingDesc}</p>
            </div>
          )}

          {/* Search Results */}
          {!searchMutation.isPending && searchMutation.data && (
            <div className="mt-6 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium">
                  {t.searchPage.resultsFound.replace(
                    "{count}",
                    searchMutation.data.total_count.toString(),
                  )}
                </h3>
                <div className="flex items-center gap-2">
                  {searchMutation.data.results.length > 0 && (
                    <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
                      <Checkbox
                        checked={groupByType}
                        onCheckedChange={(checked) => setGroupByType(checked as boolean)}
                      />
                      {t.searchPage.groupByType}
                    </label>
                  )}
                  <Badge variant="outline">
                    {searchMutation.data.search_type === "text"
                      ? t.searchPage.textSearch
                      : searchMutation.data.search_type === "hybrid"
                        ? t.searchPage.hybridSearch
                        : t.searchPage.vectorSearch}
                  </Badge>
                </div>
              </div>

              {searchMutation.data.results.length === 0 ? (
                <Card>
                  <CardContent className="pt-6 text-center text-muted-foreground">
                    {t.searchPage.noResultsFor.replace("{query}", searchQuery)}
                  </CardContent>
                </Card>
              ) : groupByType ? (
                <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
                  {groupedResults.map(([type, results]) => (
                    <div key={type} className="space-y-2">
                      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                        <FileText className="h-3.5 w-3.5" />
                        {groupLabel(type)}
                        <Badge variant="secondary" className="text-[10px]">
                          {results.length}
                        </Badge>
                      </div>
                      {results.map((result, index) => renderResult(result, `${type}-${index}`))}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-2">
                  {searchMutation.data.results.map((result, index) => renderResult(result, index))}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
      </div>
    </div>
  );
}
