"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Building2,
  ShieldCheck,
  Tag,
  FileText,
  Send,
  Sparkles,
  Loader2,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { navyDocsApi } from "@/lib/api/navy-docs";
import { useTranslation } from "@/lib/hooks/use-translation";

interface NavyDocViewerDialogProps {
  docId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  classificationLabel?: (level: number | null | undefined) => string;
}

type ChatMsg = { role: "human" | "ai"; content: string };

const MARKDOWN_CLASS =
  "text-sm leading-relaxed [&_h1]:text-base [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:mb-1 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-semibold [&_p]:my-2 [&_table]:my-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_strong]:font-semibold";

/**
 * Full viewer for a single navy/OpenSearch corpus document — content, AI
 * insights, and a RAG chat scoped to just this document. Every tab hits an
 * ACL-checked endpoint (clearance + department), so a user can only see/ask
 * about documents they are allowed to read.
 */
export function NavyDocViewerDialog({
  docId,
  open,
  onOpenChange,
  classificationLabel,
}: NavyDocViewerDialogProps) {
  const { t } = useTranslation();
  const nd = t.navyDocs;

  const [tab, setTab] = useState<"content" | "insights" | "chat">("content");
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Reset per-document state when the opened document changes.
  useEffect(() => {
    setTab("content");
    setChatMessages([]);
    setChatInput("");
    setChatError(false);
  }, [docId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, chatLoading]);

  const {
    data: content,
    isLoading: contentLoading,
    isError: contentError,
  } = useQuery({
    queryKey: ["navy-doc-content", docId],
    queryFn: () => navyDocsApi.getContent(docId as string),
    enabled: open && !!docId,
  });

  const {
    data: insights,
    isLoading: insightsLoading,
    isError: insightsError,
  } = useQuery({
    queryKey: ["navy-doc-insights", docId],
    queryFn: () => navyDocsApi.getInsights(docId as string),
    // Only generate insights when the user opens that tab (it's an LLM call).
    enabled: open && !!docId && tab === "insights",
    staleTime: Infinity,
  });

  const sendChat = async () => {
    const message = chatInput.trim();
    if (!message || !docId || chatLoading) return;
    const history = chatMessages;
    setChatMessages((prev) => [...prev, { role: "human", content: message }]);
    setChatInput("");
    setChatLoading(true);
    setChatError(false);
    try {
      const res = await navyDocsApi.chat({ doc_id: docId, message, history });
      setChatMessages((prev) => [
        ...prev,
        { role: "ai", content: res.answer || "" },
      ]);
    } catch {
      setChatError(true);
    } finally {
      setChatLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-3xl flex-col p-0">
        <DialogHeader className="border-b px-6 py-4 pr-12">
          <DialogTitle className="truncate" title={content?.title || docId || ""}>
            {content?.title || docId || ""}
          </DialogTitle>
          {content && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              {content.creator_department && (
                <Badge variant="outline" className="gap-1 text-xs">
                  <Building2 className="h-3 w-3" />
                  {content.creator_department}
                </Badge>
              )}
              {content.classification_level !== null &&
                content.classification_level !== undefined && (
                  <Badge variant="outline" className="gap-1 text-xs">
                    <ShieldCheck className="h-3 w-3" />
                    {classificationLabel
                      ? classificationLabel(content.classification_level)
                      : content.classification_level}
                  </Badge>
                )}
              {content.document_type && (
                <Badge variant="outline" className="gap-1 text-xs">
                  <Tag className="h-3 w-3" />
                  {content.document_type}
                </Badge>
              )}
            </div>
          )}
        </DialogHeader>

        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as typeof tab)}
          className="flex min-h-0 flex-1 flex-col"
        >
          <TabsList className="mx-6 mt-3 w-[calc(100%-3rem)] justify-start">
            <TabsTrigger value="content">{nd?.tabContent ?? "Content"}</TabsTrigger>
            <TabsTrigger value="insights">{nd?.tabInsights ?? "Insights"}</TabsTrigger>
            <TabsTrigger value="chat">{nd?.tabChat ?? "Chat"}</TabsTrigger>
          </TabsList>

          {/* Content */}
          <TabsContent value="content" className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            {contentLoading ? (
              <CenterSpinner label={nd?.loading ?? "Loading document..."} />
            ) : contentError || !content ? (
              <CenterError label={nd?.loadError ?? "Could not load this document."} />
            ) : content.content.trim() ? (
              <div className={MARKDOWN_CLASS}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {content.content}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="py-12 text-center text-sm text-muted-foreground">
                {nd?.empty ?? "No content available."}
              </div>
            )}
          </TabsContent>

          {/* Insights */}
          <TabsContent value="insights" className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            {insightsLoading ? (
              <CenterSpinner label={nd?.generatingInsights ?? "Generating insights..."} />
            ) : insightsError || !insights ? (
              <CenterError label={nd?.insightsError ?? "Could not generate insights."} />
            ) : (
              <div className={MARKDOWN_CLASS}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {insights.insights || (nd?.empty ?? "No content available.")}
                </ReactMarkdown>
              </div>
            )}
          </TabsContent>

          {/* Chat (RAG over this single document) */}
          <TabsContent value="chat" className="flex min-h-0 flex-1 flex-col px-6 py-3">
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
              {chatMessages.length === 0 && !chatLoading && (
                <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
                  <Sparkles className="h-7 w-7 opacity-40" />
                  <span>{nd?.chatEmpty ?? "Ask a question about this document."}</span>
                </div>
              )}
              {chatMessages.map((m, i) => (
                <div
                  key={i}
                  className={
                    m.role === "human"
                      ? "ml-auto max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                      : "mr-auto max-w-[90%] rounded-lg bg-muted px-3 py-2"
                  }
                >
                  {m.role === "ai" ? (
                    <div className={MARKDOWN_CLASS}>
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {m.content}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <span className="whitespace-pre-wrap">{m.content}</span>
                  )}
                </div>
              ))}
              {chatLoading && (
                <div className="mr-auto flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {nd?.chatThinking ?? "Thinking..."}
                </div>
              )}
              {chatError && (
                <div className="mr-auto rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {nd?.chatError ?? "Could not get an answer."}
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
            <div className="mt-3 flex flex-shrink-0 items-center gap-2 border-t pt-3">
              <Input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendChat();
                  }
                }}
                placeholder={nd?.chatPlaceholder ?? "Ask about this document..."}
                disabled={chatLoading}
                autoComplete="off"
              />
              <Button
                size="icon"
                onClick={() => void sendChat()}
                disabled={chatLoading || !chatInput.trim()}
                aria-label={nd?.tabChat ?? "Chat"}
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function CenterSpinner({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
      <LoadingSpinner />
      <span className="text-sm">{label}</span>
    </div>
  );
}

function CenterError({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center text-muted-foreground">
      <FileText className="h-8 w-8 opacity-40" />
      <span className="text-sm">{label}</span>
    </div>
  );
}
