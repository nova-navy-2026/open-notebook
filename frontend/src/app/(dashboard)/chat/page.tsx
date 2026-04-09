"use client";

import { useState } from "react";
import { useTranslation } from "@/lib/hooks/use-translation";
import { useGlobalChat } from "@/lib/hooks/useGlobalChat";
import { ChatPanel } from "@/components/source/ChatPanel";
import { Badge } from "@/components/ui/badge";
import { FileText, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function GlobalChatPage() {
  const { t } = useTranslation();
  const chat = useGlobalChat();
  const [docsExpanded, setDocsExpanded] = useState(false);

  const documents = chat.contextStats?.documents ?? [];

  return (
    <div className="flex flex-col h-full p-4 md:p-6">
      <div className="mb-4">
        <h1 className="text-2xl font-bold">{t.common.chat ?? "Chat"}</h1>
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

      {/* Full-height chat panel */}
      <div className="flex-1 min-h-0">
        <ChatPanel
          messages={chat.messages}
          isStreaming={chat.isSending}
          contextIndicators={null}
          onSendMessage={chat.sendMessage}
          modelOverride={
            chat.currentSession?.model_override ?? chat.pendingModelOverride ?? undefined
          }
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
          title={t.common.chat ?? "Chat"}
          contextType="notebook"
        />
      </div>
    </div>
  );
}
