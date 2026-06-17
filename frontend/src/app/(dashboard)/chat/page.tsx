"use client";

import { useState } from "react";
import { useTranslation } from "@/lib/hooks/use-translation";
import { useIsDesktop } from "@/lib/hooks/use-media-query";
import { useGlobalChat } from "@/lib/hooks/useGlobalChat";
import { useModels } from "@/lib/hooks/use-models";
import { ChatPanel } from "@/components/source/ChatPanel";
import { ChatSessionRail } from "@/components/source/ChatSessionRail";
import { useChatLayoutStore } from "@/lib/stores/chat-layout-store";
import { Badge } from "@/components/ui/badge";
import { FileText, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { globalChatApi } from "@/lib/api/global-chat";
import { PageInfoButton } from "@/components/common/PageInfoButton";
import {
  conversationsToMarkdown,
  downloadMarkdown,
  type ExportableConversation,
} from "@/lib/utils/export-markdown";
import { toast } from "sonner";

export default function GlobalChatPage() {
  const { t } = useTranslation();
  const chat = useGlobalChat();
  const { data: models = [] } = useModels();
  const { sessionRailCollapsed, toggleSessionRail } = useChatLayoutStore();
  const isDesktop = useIsDesktop();
  const [docsExpanded, setDocsExpanded] = useState(false);
  const [exportingAll, setExportingAll] = useState(false);

  const handleExportAll = async () => {
    if (exportingAll) return;
    setExportingAll(true);
    try {
      const sessions = await globalChatApi.listSessions();
      if (!sessions.length) {
        toast.info(t.chat.noConversationsToExport ?? "Não há conversas para exportar");
        return;
      }
      const detailed = await Promise.all(
        sessions.map((session) => globalChatApi.getSession(session.id).catch(() => null)),
      );
      const conversations: ExportableConversation[] = detailed
        .filter((session): session is NonNullable<typeof session> => Boolean(session))
        .map((session) => ({
          title: session.title || "Conversa",
          messages: session.messages ?? [],
          createdAt: session.created,
          updatedAt: session.updated,
        }));
      if (!conversations.length) {
        toast.info(t.chat.noConversationsToExport ?? "Não há conversas para exportar");
        return;
      }
      const markdown = conversationsToMarkdown(
        conversations,
        t.chat.exportAllConversations ?? "Conversas exportadas",
      );
      downloadMarkdown(markdown, "conversas");
      toast.success(t.chat.conversationsExported ?? "Conversas exportadas");
    } catch (error) {
      console.error("Failed to export conversations:", error);
      toast.error(t.chat.exportFailed ?? "Falha ao exportar conversas");
    } finally {
      setExportingAll(false);
    }
  };

  const documents = chat.contextStats?.documents ?? [];
  const gemmaModel = models.find((model) => {
    const provider = model.provider?.toLowerCase() ?? "";
    const name = model.name?.toLowerCase() ?? "";
    const id = model.id?.toLowerCase() ?? "";
    return model.type === "language" && (
      provider === "gemma" || name.includes("gemma") || id.includes("gemma")
    );
  });
  const activeModelOverride = chat.isVisualModelLocked
    ? gemmaModel?.id
    : chat.currentSession?.model_override ?? chat.pendingModelOverride ?? undefined;

  return (
    // OpenWebUI-style two-column workspace: a persistent chat-history rail on
    // the left (the global menu is auto-collapsed to its icon rail by AppShell),
    // and the conversation on the right.
    <div className="flex h-full w-full min-h-0">
      {/* Session rail: desktop only. On mobile the session tab inside ChatPanel
          remains available (see hideSessionTab below), so nothing is lost. */}
      <div className="hidden lg:flex h-full flex-shrink-0">
        <ChatSessionRail
          sessions={chat.sessions}
          currentSessionId={chat.currentSessionId ?? null}
          loading={chat.loadingSessions}
          collapsed={sessionRailCollapsed}
          onToggleCollapsed={toggleSessionRail}
          onNewChat={() => chat.startNewChat()}
          onSelectSession={chat.switchSession}
          onRenameSession={(sessionId, title) =>
            chat.updateSession(sessionId, { title })
          }
          onDeleteSession={chat.deleteSession}
        />
      </div>

      <div className="min-w-0 flex-1 app-page-wide flex h-full flex-col">
      <div className="mb-4">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold">{t.common.chat ?? "Chat"}</h1>
          <PageInfoButton pageKey="chat" />
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          {t.chat.globalChatDescription ?? "Chat with all your indexed documents"}
        </p>
      </div>

      {/* Context stats badges */}
      {documents.length > 0 && (
        <div className="mb-3">
          <Button
            variant="ghost"
            size="sm"
            className="gap-1 px-2 h-7 text-xs text-muted-foreground"
            onClick={() => setDocsExpanded(!docsExpanded)}
          >
            <Badge variant="outline" className="gap-1 mr-1">
              <FileText className="h-3 w-3" />
              {documents.length} {documents.length === 1 ? "doc" : "docs"}
            </Badge>
            {docsExpanded ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
          </Button>

          {docsExpanded && (
            <div className="mt-2 rounded-md border p-3 text-xs max-h-48 overflow-y-auto">
              <ul className="space-y-0.5">
                {documents.map((doc, i) => (
                  <li key={i} className="text-foreground">
                    {doc.name}
                    {doc.pages.length > 0 && (
                      <span className="text-muted-foreground ml-1">
                        (p. {doc.pages.join(", ")})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Full-height chat panel. On desktop the session rail (left) owns session
          switching, so the panel's own session tab is hidden; on mobile the rail
          is hidden and the in-panel tab takes over. */}
      <div className="flex-1 min-h-0">
        <ChatPanel
          messages={chat.messages}
          isStreaming={chat.isSending}
          contextIndicators={null}
          onSendMessage={chat.sendMessage}
          modelOverride={activeModelOverride}
          onModelChange={(model) => chat.setModelOverride(model ?? null)}
          sessions={chat.sessions}
          currentSessionId={chat.currentSessionId}
          onCreateSession={(title) => chat.createSession(title)}
          onSelectSession={chat.switchSession}
          onDeleteSession={chat.deleteSession}
          onUpdateSession={(sessionId, title) =>
            chat.updateSession(sessionId, { title })
          }
          loadingSessions={chat.loadingSessions}
          hideSessionTab={isDesktop}
          title={t.common.chat ?? "Chat"}
          contextType="notebook"
          enableAttachments
          visualModelLocked={chat.isVisualModelLocked}
          enableDeepResearch
          enableAgentControls
          onExportAll={handleExportAll}
          exportingAll={exportingAll}
        />
      </div>
      </div>
    </div>
  );
}
