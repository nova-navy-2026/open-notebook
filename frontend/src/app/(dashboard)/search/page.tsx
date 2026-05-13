"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import { Search, ChevronDown } from "lucide-react";
import { useSearch } from "@/lib/hooks/use-search";
import { useSettings } from "@/lib/hooks/use-settings";
import { useModelDefaults } from "@/lib/hooks/use-models";
import { useModalManager } from "@/lib/hooks/use-modal-manager";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";

export default function SearchPage() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const urlQuery = searchParams?.get("q") || "";

  // Search state
  const [searchQuery, setSearchQuery] = useState(urlQuery);
  const [searchSources, setSearchSources] = useState(true);
  const [searchNotes, setSearchNotes] = useState(true);

  // Hooks
  const searchMutation = useSearch();
  const { data: settings } = useSettings();
  const { data: modelDefaults, isLoading: modelsLoading } = useModelDefaults();
  const { openModal } = useModalManager();

  const hasEmbeddingModel = !!modelDefaults?.default_embedding_model;

  // Determine search type from admin settings, falling back to hybrid or text
  const searchType: "text" | "vector" | "hybrid" = (() => {
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

  const hasAutoTriggeredRef = useRef(false);

  const handleSearch = useCallback(() => {
    if (!searchQuery.trim()) return;

    searchMutation.mutate({
      query: searchQuery,
      type: searchType,
      limit: 10,
      search_sources: searchSources,
      search_notes: searchNotes,
      minimum_score: 0.2,
    });
  }, [searchQuery, searchType, searchSources, searchNotes, searchMutation]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSearch();
    }
  };

  // Auto-trigger search from URL params
  useEffect(() => {
    if (hasAutoTriggeredRef.current || !urlQuery) return;
    handleSearch();
    hasAutoTriggeredRef.current = true;
  }, [urlQuery, handleSearch]);

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 md:p-6">
      <h1 className="text-xl md:text-2xl font-bold mb-4 md:mb-6">
        {t.searchPage.search}
      </h1>

      <Card>
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
            <div className="flex flex-col sm:flex-row gap-2">
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
          </div>

          {/* Search Options */}
          <div className="space-y-4">
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
              <div className="space-y-2">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="sources"
                    name="sources"
                    checked={searchSources}
                    onCheckedChange={(checked) =>
                      setSearchSources(checked as boolean)
                    }
                    disabled={searchMutation.isPending}
                  />
                  <Label
                    htmlFor="sources"
                    className="font-normal cursor-pointer"
                  >
                    {t.searchPage.searchSources}
                  </Label>
                </div>
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="notes"
                    name="notes"
                    checked={searchNotes}
                    onCheckedChange={(checked) =>
                      setSearchNotes(checked as boolean)
                    }
                    disabled={searchMutation.isPending}
                  />
                  <Label htmlFor="notes" className="font-normal cursor-pointer">
                    {t.searchPage.searchNotes}
                  </Label>
                </div>
              </div>
            </div>
          </div>

          {/* Search Results */}
          {searchMutation.data && (
            <div className="mt-6 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium">
                  {t.searchPage.resultsFound.replace(
                    "{count}",
                    searchMutation.data.total_count.toString(),
                  )}
                </h3>
                <Badge variant="outline">
                  {searchMutation.data.search_type === "text"
                    ? t.searchPage.textSearch
                    : searchMutation.data.search_type === "hybrid"
                      ? t.searchPage.hybridSearch
                      : t.searchPage.vectorSearch}
                </Badge>
              </div>

              {searchMutation.data.results.length === 0 ? (
                <Card>
                  <CardContent className="pt-6 text-center text-muted-foreground">
                    {t.searchPage.noResultsFor.replace("{query}", searchQuery)}
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-2">
                  {searchMutation.data.results.map((result, index) => {
                    if (!result.parent_id) {
                      console.warn(
                        "Search result with null parent_id:",
                        result,
                      );
                      return null;
                    }
                    const [type, id] = result.parent_id.split(":");
                    const isNavy = type === "navy";
                    const modalType = isNavy
                      ? null
                      : type === "source_insight"
                        ? "insight"
                        : (type as "source" | "note" | "insight");
                    const typeLabel = isNavy
                      ? "Document"
                      : type === "source"
                        ? "Source"
                        : type === "note"
                          ? "Note"
                          : "Insight";

                    const matchCount = result.matches?.length ?? 0;

                    return (
                      <Card
                        key={index}
                        className="hover:border-primary/30 transition-colors"
                      >
                        <CardContent className="pt-4">
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <Badge
                                  variant="outline"
                                  className="text-xs flex-shrink-0"
                                >
                                  {typeLabel}
                                </Badge>
                                <Badge
                                  variant="secondary"
                                  className="text-xs flex-shrink-0"
                                >
                                  {result.final_score.toFixed(2)}
                                </Badge>
                                {matchCount > 1 && (
                                  <Badge
                                    variant="secondary"
                                    className="text-xs flex-shrink-0"
                                  >
                                    {matchCount} chunks
                                  </Badge>
                                )}
                              </div>
                              {modalType ? (
                                <button
                                  onClick={() => openModal(modalType, id)}
                                  className="text-primary hover:underline font-medium text-left truncate block w-full"
                                >
                                  {result.title}
                                </button>
                              ) : (
                                <span
                                  className="font-medium text-left truncate block w-full"
                                  title={result.title}
                                >
                                  {result.title}
                                </span>
                              )}
                            </div>
                          </div>

                          {result.matches && result.matches.length > 0 && (
                            <Collapsible className="mt-3">
                              <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
                                <ChevronDown className="h-4 w-4" />
                                {t.searchPage.matches.replace(
                                  "{count}",
                                  result.matches.length.toString(),
                                )}
                              </CollapsibleTrigger>
                              <CollapsibleContent className="mt-2 space-y-1">
                                {result.matches.map((match, i) => (
                                  <div
                                    key={i}
                                    className="text-sm pl-6 py-1 border-l-2 border-muted"
                                  >
                                    {match}
                                  </div>
                                ))}
                              </CollapsibleContent>
                            </Collapsible>
                          )}
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
