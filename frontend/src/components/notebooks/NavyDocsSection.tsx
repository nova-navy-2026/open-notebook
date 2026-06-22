"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useNavyDocuments } from "@/lib/hooks/use-navy-docs";
import type { NavyDocument } from "@/lib/api/navy-docs";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Database,
  Search,
  Loader2,
  FileText,
  Building2,
  ShieldCheck,
  Tag,
  RefreshCw,
  AlertCircle,
  ListChecks,
  X,
} from "lucide-react";
import { useTranslation } from "@/lib/hooks/use-translation";
import { cn } from "@/lib/utils";

const MAX_SELECTED = 15;
const PAGE_SIZE = 20;

type GroupByKey = "department" | "classification" | "type" | "none";

interface DocGroup {
  key: string;
  label: string;
  docs: NavyDocument[];
}

interface NavyDocsSectionProps {
  /** Set of selected doc_ids (all selected by default) */
  selectedDocIds?: Set<string>;
  /** Called when user toggles a document */
  onSelectionChange?: (docId: string, selected: boolean) => void;
  /**
   * @deprecated No longer used. Bulk select was removed because the corpus
   * selection is capped at {@link MAX_SELECTED}. Kept optional so existing
   * callers compile.
   */
  onSelectAll?: (selected: boolean) => void;
  /** When true, hide checkboxes and show a read-only catalog */
  readOnly?: boolean;
}

export function NavyDocsSection({
  selectedDocIds,
  onSelectionChange,
  readOnly = false,
}: NavyDocsSectionProps) {
  const { t } = useTranslation();
  const { data, isLoading, error, refetch, isFetching } = useNavyDocuments();
  const [isOpen, setIsOpen] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [groupBy, setGroupBy] = useState<GroupByKey>("department");
  // Track which groups the user has explicitly OPENED (empty = all collapsed).
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  // Collapse all groups whenever the grouping dimension changes.
  useEffect(() => {
    setExpandedGroups(new Set());
  }, [groupBy]);

  const documents = useMemo(() => data?.documents ?? [], [data]);

  const classificationLabel = useCallback(
    (level: number | null | undefined): string => {
      if (level === null || level === undefined) {
        return t.navyDocs?.unclassified ?? "Unclassified";
      }
      return `${t.navyDocs?.classificationLevel ?? "Level"} ${level}`;
    },
    [t],
  );

  const filteredDocs = useMemo(() => {
    if (!searchQuery.trim()) return documents;
    const q = searchQuery.toLowerCase();
    return documents.filter(
      (d) =>
        d.doc_id.toLowerCase().includes(q) ||
        d.source.toLowerCase().includes(q) ||
        d.sample_section.toLowerCase().includes(q) ||
        (d.creator_department ?? "").toLowerCase().includes(q) ||
        (d.document_type ?? "").toLowerCase().includes(q),
    );
  }, [documents, searchQuery]);

  // Build the hierarchical groups for the current grouping dimension.
  const groups = useMemo<DocGroup[]>(() => {
    if (groupBy === "none") return [];

    const buckets = new Map<string, DocGroup>();
    for (const doc of filteredDocs) {
      let key: string;
      let label: string;
      if (groupBy === "department") {
        key = doc.creator_department ?? "";
        label = key || (t.navyDocs?.noDepartment ?? "No department");
      } else if (groupBy === "classification") {
        key =
          doc.classification_level === null ||
          doc.classification_level === undefined
            ? ""
            : String(doc.classification_level);
        label = classificationLabel(doc.classification_level);
      } else {
        key = doc.document_type ?? "";
        label = key || (t.navyDocs?.otherType ?? "Other");
      }
      const existing = buckets.get(key);
      if (existing) {
        existing.docs.push(doc);
      } else {
        buckets.set(key, { key, label, docs: [doc] });
      }
    }

    const sorted = Array.from(buckets.values());
    if (groupBy === "classification") {
      sorted.sort((a, b) => {
        const av = a.key === "" ? Number.POSITIVE_INFINITY : Number(a.key);
        const bv = b.key === "" ? Number.POSITIVE_INFINITY : Number(b.key);
        return av - bv;
      });
    } else {
      sorted.sort((a, b) => a.label.localeCompare(b.label));
    }
    return sorted;
  }, [filteredDocs, groupBy, t, classificationLabel]);


  // Reset to page 1 when search changes
  const totalPages = Math.max(1, Math.ceil(filteredDocs.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedDocs = filteredDocs.slice(
    (safePage - 1) * PAGE_SIZE,
    safePage * PAGE_SIZE,
  );

  const selectedCount = selectedDocIds?.size ?? 0;
  const atLimit = selectedCount >= MAX_SELECTED;

  // Human-friendly label for a document id (drops the .pdf and underscores).
  const docLabel = useCallback(
    (doc: NavyDocument) =>
      doc.doc_id.replace(/_/g, " ").replace(/\.pdf$/i, ""),
    [],
  );

  // The documents currently selected, surfaced in their own section so the
  // user always sees what's in their selection regardless of search/grouping.
  const selectedDocs = useMemo(
    () => documents.filter((d) => selectedDocIds?.has(d.doc_id)),
    [documents, selectedDocIds],
  );

  const toggleGroup = (key: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Renders one document row (icon + optional checkbox + label + metadata).
  const renderDocRow = (doc: NavyDocument) => {
    const isSelected = selectedDocIds?.has(doc.doc_id) ?? false;
    const label = docLabel(doc);
    const disabledByLimit = !isSelected && atLimit;

    return (
      <div
        key={doc.doc_id}
        className={cn(
          "flex items-start gap-2 px-2 py-1.5 rounded transition-colors",
          readOnly
            ? ""
            : disabledByLimit
              ? "opacity-50 cursor-not-allowed"
              : "hover:bg-accent/50 cursor-pointer",
        )}
      >
        {!readOnly && onSelectionChange && (
          <Checkbox
            checked={isSelected}
            onCheckedChange={(checked) =>
              onSelectionChange(doc.doc_id, !!checked)
            }
            disabled={disabledByLimit}
            className="mt-0.5"
          />
        )}
        <FileText className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate" title={doc.doc_id}>
            {label}
          </div>
          <div className="flex flex-wrap items-center gap-1 mt-0.5">
            {doc.creator_department && groupBy !== "department" && (
              <Badge variant="outline" className="text-[10px] px-1 py-0 gap-0.5">
                <Building2 className="h-2.5 w-2.5" />
                {doc.creator_department}
              </Badge>
            )}
            {doc.classification_level !== null &&
              doc.classification_level !== undefined &&
              groupBy !== "classification" && (
                <Badge variant="outline" className="text-[10px] px-1 py-0 gap-0.5">
                  <ShieldCheck className="h-2.5 w-2.5" />
                  {classificationLabel(doc.classification_level)}
                </Badge>
              )}
            {doc.document_type && groupBy !== "type" && (
              <Badge variant="outline" className="text-[10px] px-1 py-0 gap-0.5">
                <Tag className="h-2.5 w-2.5" />
                {doc.document_type}
              </Badge>
            )}
          </div>
        </div>
      </div>
    );
  };

  if (isLoading) {
    return (
      <div className="border rounded-lg p-3 mt-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>{t.navyDocs?.loading ?? "Loading corpus documents..."}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="border rounded-lg p-3 mt-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span>{t.navyDocs?.loadError ?? "Erro ao carregar base de conhecimento"}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 gap-1 text-xs"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            {t.common?.retry ?? "Tentar novamente"}
          </Button>
        </div>
      </div>
    );
  }

  if (!documents.length) {
    return null; // User has no accessible corpus documents — don't show the section
  }

  return (
    <div className="border rounded-lg mt-3">
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger asChild>
          <button className="flex items-center justify-between w-full p-3 hover:bg-accent/50 rounded-t-lg transition-colors">
            <div className="flex items-center gap-2">
              {isOpen ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
              <Database className="h-4 w-4 text-primary" />
              <span className="font-medium text-sm">
                {t.navyDocs?.title ?? "Knowledge Base"}
              </span>
              <Badge variant="secondary" className="text-xs">
                {readOnly
                  ? `${documents.length}`
                  : `${selectedCount}/${MAX_SELECTED}`}
              </Badge>
            </div>
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-3 pb-3 space-y-2">
            {/* Currently selected documents — always visible so the user can
                see and trim their selection regardless of search / grouping. */}
            {!readOnly && selectedDocs.length > 0 && (
              <div className="rounded-md border border-primary/30 bg-primary/5 p-2 space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
                  <ListChecks className="h-3.5 w-3.5" />
                  <span>{t.navyDocs?.selectedTitle ?? "Selected documents"}</span>
                  <Badge variant="secondary" className="text-[10px] px-1 py-0">
                    {selectedCount}/{MAX_SELECTED}
                  </Badge>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {selectedDocs.map((doc) => (
                    <span
                      key={doc.doc_id}
                      className="inline-flex items-center gap-1 max-w-full rounded-full border bg-background pl-2 pr-1 py-0.5 text-xs"
                    >
                      <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                      <span
                        className="truncate max-w-[150px]"
                        title={doc.doc_id}
                      >
                        {docLabel(doc)}
                      </span>
                      {onSelectionChange && (
                        <button
                          type="button"
                          onClick={() => onSelectionChange(doc.doc_id, false)}
                          className="rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                          aria-label={t.common?.remove ?? "Remove"}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Controls: limit notice / group-by / search */}
            <div className="flex items-center gap-2">
              {!readOnly && atLimit && (
                <span className="text-xs text-amber-600 dark:text-amber-500">
                  Max {MAX_SELECTED} reached
                </span>
              )}
              <div className="flex-1" />
              <Select
                value={groupBy}
                onValueChange={(v) => setGroupBy(v as GroupByKey)}
              >
                <SelectTrigger className="h-7 w-36 text-xs">
                  <SelectValue placeholder={t.navyDocs?.groupBy ?? "Group by"} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="department">
                    {t.navyDocs?.groupByDepartment ?? "Department"}
                  </SelectItem>
                  <SelectItem value="classification">
                    {t.navyDocs?.groupByClassification ?? "Classification"}
                  </SelectItem>
                  <SelectItem value="type">
                    {t.navyDocs?.groupByType ?? "Type"}
                  </SelectItem>
                  <SelectItem value="none">
                    {t.navyDocs?.groupByNone ?? "None"}
                  </SelectItem>
                </SelectContent>
              </Select>
              <div className="relative w-40">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                <Input
                  placeholder={t.navyDocs?.filter ?? "Filter..."}
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="h-7 pl-7 text-xs"
                />
              </div>
            </div>

            {/* Grouped document tree (hierarchical) */}
            {groupBy !== "none" ? (
              <div className="space-y-1">
                {groups.map((group) => {
                  const groupCollapsed = !expandedGroups.has(group.key);
                  return (
                    <div key={group.key || "__none__"}>
                      <button
                        type="button"
                        onClick={() => toggleGroup(group.key)}
                        className="flex items-center gap-1.5 w-full px-1 py-1 rounded hover:bg-accent/50 transition-colors"
                      >
                        {groupCollapsed ? (
                          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                        )}
                        {groupBy === "department" ? (
                          <Building2 className="h-3.5 w-3.5 text-primary" />
                        ) : groupBy === "classification" ? (
                          <ShieldCheck className="h-3.5 w-3.5 text-primary" />
                        ) : (
                          <Tag className="h-3.5 w-3.5 text-primary" />
                        )}
                        <span className="text-xs font-semibold truncate">
                          {group.label}
                        </span>
                        <Badge
                          variant="secondary"
                          className="text-[10px] px-1 py-0 ml-1"
                        >
                          {group.docs.length}
                        </Badge>
                      </button>
                      {!groupCollapsed && (
                        <div className="ml-4 border-l pl-2 space-y-0.5">
                          {group.docs.map((doc) => renderDocRow(doc))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <>
                {/* Flat list — paginated */}
                <div className="space-y-1">
                  {pagedDocs.map((doc) => renderDocRow(doc))}
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between pt-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      disabled={safePage <= 1}
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    >
                      <ChevronLeft className="h-3 w-3 mr-1" />
                      {t.navyDocs?.prev ?? "Prev"}
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      {safePage} / {totalPages}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      disabled={safePage >= totalPages}
                      onClick={() =>
                        setCurrentPage((p) => Math.min(totalPages, p + 1))
                      }
                    >
                      {t.navyDocs?.next ?? "Next"}
                      <ChevronRight className="h-3 w-3 ml-1" />
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
