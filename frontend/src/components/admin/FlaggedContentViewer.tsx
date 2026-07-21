"use client";

import { useCallback, useEffect, useState } from "react";
import { formatDateTime } from "@/lib/utils/format-datetime";
import { apiClient } from "@/lib/api/client";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { AlertCircle, ShieldAlert, Eye, Check, X, Trash2 } from "lucide-react";

interface ContentFlag {
  id: string;
  content_type: "chat_message" | "assistant_message" | "source" | "note";
  content_id: string;
  notebook_id?: string | null;
  session_id?: string | null;
  title?: string | null;
  excerpt?: string | null;
  user_id?: string | null;
  user_email?: string | null;
  navy_user_id?: string | null;
  departments?: string[];
  clearance_level?: number | null;
  categories: string[];
  severity: "low" | "medium" | "high";
  reason?: string | null;
  status: "open" | "reviewed" | "dismissed";
  reviewed_by?: string | null;
  review_note?: string | null;
  created?: string;
  content_snapshot?: string | null;
  original_deleted?: boolean;
  original_deleted_at?: string | null;
}

interface ConversationMessage {
  type: string;
  content: string;
}

const CONTENT_TYPE_LABEL: Record<string, string> = {
  chat_message: "User message",
  assistant_message: "AI reply",
  source: "Uploaded document",
  note: "Note",
};

const CATEGORY_LABEL: Record<string, string> = {
  classified_leak: "Classified leakage",
  threat_violence: "Threat / violence",
  exfiltration_opsec: "Exfiltration / OPSEC",
  illegal_misconduct: "Illegal / misconduct",
  user_disliked: "User feedback: not helpful",
};

function severityVariant(
  severity: string,
): "destructive" | "secondary" | "outline" {
  if (severity === "high") return "destructive";
  if (severity === "medium") return "secondary";
  return "outline";
}

export function FlaggedContentViewer() {
  const [flags, setFlags] = useState<ContentFlag[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("open");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");

  const [selected, setSelected] = useState<ContentFlag | null>(null);
  const [conversation, setConversation] = useState<ConversationMessage[] | null>(
    null,
  );
  const [conversationLoading, setConversationLoading] = useState(false);
  const [conversationIsSnapshot, setConversationIsSnapshot] = useState(false);

  const fetchFlags = useCallback(async () => {
    try {
      setIsLoading(true);
      const params = new URLSearchParams();
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (severityFilter !== "all") params.set("severity", severityFilter);
      if (typeFilter !== "all") params.set("content_type", typeFilter);
      if (categoryFilter !== "all") params.set("category", categoryFilter);

      const response = await apiClient.get<{ flags: ContentFlag[] }>(
        `/flags?${params.toString()}`,
      );
      setFlags(response.data?.flags ?? []);
      setError(null);
    } catch (err: any) {
      const message =
        err?.response?.data?.detail ||
        err?.message ||
        "Failed to fetch flagged content";
      console.error("Flags fetch error:", err);
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter, severityFilter, typeFilter, categoryFilter]);

  useEffect(() => {
    fetchFlags();
  }, [fetchFlags]);

  const openFlag = async (flag: ContentFlag) => {
    setSelected(flag);
    setConversation(null);

    // Chat flags can be opened in full; other content types only expose the
    // stored excerpt.
    if (
      flag.content_type !== "chat_message" &&
      flag.content_type !== "assistant_message"
    ) {
      return;
    }
    try {
      setConversationLoading(true);
      const response = await apiClient.get<{
        messages: ConversationMessage[];
        source?: string;
      }>(`/flags/${encodeURIComponent(flag.id)}/conversation`);
      setConversation(response.data?.messages ?? []);
      setConversationIsSnapshot(response.data?.source === "snapshot");
    } catch (err) {
      console.error("Conversation fetch error:", err);
      setConversation([]);
    } finally {
      setConversationLoading(false);
    }
  };

  const review = async (flag: ContentFlag, status: "reviewed" | "dismissed") => {
    try {
      await apiClient.put(`/flags/${encodeURIComponent(flag.id)}/review`, {
        status,
      });
      setSelected(null);
      fetchFlags();
    } catch (err: any) {
      alert(
        err?.response?.data?.detail || err?.message || "Failed to update flag",
      );
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5" />
          Flagged Content
        </CardTitle>
        <CardDescription>
          Content automatically flagged as potentially dangerous. This is the
          only user content visible to administrators — everything else stays
          private to its owner.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger>
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">Open</SelectItem>
              <SelectItem value="reviewed">Reviewed</SelectItem>
              <SelectItem value="dismissed">Dismissed</SelectItem>
              <SelectItem value="all">All statuses</SelectItem>
            </SelectContent>
          </Select>

          <Select value={severityFilter} onValueChange={setSeverityFilter}>
            <SelectTrigger>
              <SelectValue placeholder="Severity" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All severities</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="low">Low</SelectItem>
            </SelectContent>
          </Select>

          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger>
              <SelectValue placeholder="Content type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              <SelectItem value="chat_message">User messages</SelectItem>
              <SelectItem value="assistant_message">AI replies</SelectItem>
              <SelectItem value="source">Documents</SelectItem>
              <SelectItem value="note">Notes</SelectItem>
            </SelectContent>
          </Select>

          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger>
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              <SelectItem value="user_disliked">User feedback: not helpful</SelectItem>
              <SelectItem value="classified_leak">Classified leakage</SelectItem>
              <SelectItem value="threat_violence">Threat / violence</SelectItem>
              <SelectItem value="exfiltration_opsec">Exfiltration / OPSEC</SelectItem>
              <SelectItem value="illegal_misconduct">Illegal / misconduct</SelectItem>
            </SelectContent>
          </Select>

          <Button variant="outline" onClick={fetchFlags}>
            Refresh
          </Button>
        </div>

        {error ? (
          <div className="flex items-start gap-2 text-red-600 text-sm">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : isLoading ? (
          <LoadingSpinner />
        ) : flags.length === 0 ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            No flagged content. Nothing requires review.
          </div>
        ) : (
          <ScrollArea className="border rounded-lg">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Categories</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {flags.map((flag) => (
                  <TableRow key={flag.id}>
                    <TableCell className="whitespace-nowrap text-xs">
                      {flag.created ? formatDateTime(flag.created) : "—"}
                    </TableCell>
                    <TableCell className="text-xs">
                      <div>{flag.user_email || flag.user_id || "unknown"}</div>
                      {flag.navy_user_id && (
                        <div className="text-muted-foreground">
                          {flag.navy_user_id}
                          {flag.clearance_level != null &&
                            ` · NC${flag.clearance_level}`}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">
                      {CONTENT_TYPE_LABEL[flag.content_type] ||
                        flag.content_type}
                      {flag.original_deleted && (
                        <div
                          className="flex items-center gap-1 text-amber-600 mt-0.5"
                          title="The user deleted the original; this evidence was preserved."
                        >
                          <Trash2 className="h-3 w-3" />
                          <span>deleted by user</span>
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {flag.categories.map((c) => (
                          <Badge
                            key={c}
                            variant="outline"
                            className="text-[10px]"
                          >
                            {CATEGORY_LABEL[c] || c}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={severityVariant(flag.severity)}>
                        {flag.severity}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs capitalize">
                      {flag.status}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => openFlag(flag)}
                      >
                        <Eye className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollArea>
        )}
      </CardContent>

      <Dialog
        open={!!selected}
        onOpenChange={(open) => !open && setSelected(null)}
      >
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <ShieldAlert className="h-5 w-5" />
                  {CONTENT_TYPE_LABEL[selected.content_type] ||
                    selected.content_type}
                  <Badge variant={severityVariant(selected.severity)}>
                    {selected.severity}
                  </Badge>
                </DialogTitle>
                <DialogDescription>
                  {selected.user_email || selected.user_id || "unknown user"}
                  {selected.created && ` · ${formatDateTime(selected.created)}`}
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                {selected.original_deleted && (
                  <div className="flex items-start gap-2 text-sm text-amber-700 bg-amber-50 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-300 dark:border-amber-800 rounded-md p-3">
                    <Trash2 className="h-4 w-4 mt-0.5 flex-shrink-0" />
                    <span>
                      The user deleted the original
                      {selected.original_deleted_at
                        ? ` on ${formatDateTime(selected.original_deleted_at)}`
                        : ""}
                      . The evidence below was preserved when the content was
                      flagged and is retained independently of the user&apos;s copy.
                    </span>
                  </div>
                )}

                <div>
                  <h4 className="text-sm font-medium mb-1">Why it was flagged</h4>
                  <p className="text-sm text-muted-foreground">
                    {selected.reason || "No reason recorded."}
                  </p>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {selected.categories.map((c) => (
                      <Badge key={c} variant="outline">
                        {CATEGORY_LABEL[c] || c}
                      </Badge>
                    ))}
                  </div>
                </div>

                {selected.title && (
                  <div>
                    <h4 className="text-sm font-medium mb-1">Title</h4>
                    <p className="text-sm text-muted-foreground">
                      {selected.title}
                    </p>
                  </div>
                )}

                <div>
                  <h4 className="text-sm font-medium mb-1">Flagged excerpt</h4>
                  <pre className="text-xs bg-muted p-3 rounded-md whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
                    {selected.excerpt || "(no excerpt stored)"}
                  </pre>
                </div>

                {selected.content_snapshot &&
                  selected.content_snapshot !== selected.excerpt && (
                    <div>
                      <h4 className="text-sm font-medium mb-1">
                        Preserved full content
                      </h4>
                      <pre className="text-xs bg-muted p-3 rounded-md whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
                        {selected.content_snapshot}
                      </pre>
                    </div>
                  )}

                {(selected.content_type === "chat_message" ||
                  selected.content_type === "assistant_message") && (
                  <div>
                    <h4 className="text-sm font-medium mb-1">
                      Full conversation
                      {conversationIsSnapshot && (
                        <span className="ml-2 font-normal text-xs text-amber-600">
                          (preserved snapshot — live copy no longer exists)
                        </span>
                      )}
                    </h4>
                    {conversationLoading ? (
                      <LoadingSpinner />
                    ) : conversation && conversation.length > 0 ? (
                      <div className="space-y-2 max-h-72 overflow-y-auto border rounded-md p-3">
                        {conversation.map((m, i) => (
                          <div key={i} className="text-xs">
                            <span className="font-medium">
                              {m.type === "human" ? "User" : "AI"}:
                            </span>{" "}
                            <span className="text-muted-foreground whitespace-pre-wrap break-words">
                              {m.content}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Conversation not available.
                      </p>
                    )}
                  </div>
                )}

                <div className="flex gap-2 justify-end pt-2">
                  <Button
                    variant="outline"
                    onClick={() => review(selected, "dismissed")}
                  >
                    <X className="h-4 w-4 mr-2" />
                    Dismiss (false alarm)
                  </Button>
                  <Button onClick={() => review(selected, "reviewed")}>
                    <Check className="h-4 w-4 mr-2" />
                    Mark reviewed
                  </Button>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
