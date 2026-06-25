"use client";

import { useCallback, useMemo, useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  MessageCircleQuestion,
  AlertCircle,
  Settings,
  Save,
} from "lucide-react";
import { useAsk } from "@/lib/hooks/use-ask";
import { useModelDefaults, useModels } from "@/lib/hooks/use-models";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { StreamingResponse } from "@/components/search/StreamingResponse";
import { AdvancedModelsDialog } from "@/components/search/AdvancedModelsDialog";
import { SaveToNotebooksDialog } from "@/components/search/SaveToNotebooksDialog";

/**
 * Standalone "Ask your knowledge base" panel. Extracted from the admin
 * dashboard's Ask tab so it can be reused inside the Settings modal.
 */
export function AskPanel() {
  const [askQuestion, setAskQuestion] = useState("");
  const [showAdvancedModels, setShowAdvancedModels] = useState(false);
  const [customModels, setCustomModels] = useState<{
    strategy: string;
    answer: string;
    finalAnswer: string;
  } | null>(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);

  const ask = useAsk();
  const { data: modelDefaults } = useModelDefaults();
  const { data: availableModels } = useModels();

  const modelNameById = useMemo(() => {
    if (!availableModels) return new Map<string, string>();
    return new Map(availableModels.map((model) => [model.id, model.name]));
  }, [availableModels]);

  const resolveModelName = (id?: string | null) => {
    if (!id) return "Not set";
    return modelNameById.get(id) ?? id;
  };

  const hasEmbeddingModel = !!modelDefaults?.default_embedding_model;

  const handleAsk = useCallback(() => {
    if (!askQuestion.trim() || !modelDefaults?.default_chat_model) return;

    const models = customModels || {
      strategy: modelDefaults.default_chat_model,
      answer: modelDefaults.default_chat_model,
      finalAnswer: modelDefaults.default_chat_model,
    };

    ask.sendAsk(askQuestion, models);
  }, [askQuestion, modelDefaults, customModels, ask]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <MessageCircleQuestion className="h-5 w-5" />
          Ask Your Knowledge Base
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Ask questions and get AI-powered answers from your sources and notes.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Question Input */}
        <div className="space-y-2">
          <Label htmlFor="ask-question">Question</Label>
          <Textarea
            id="ask-question"
            name="ask-question"
            placeholder="Enter your question..."
            value={askQuestion}
            onChange={(e) => setAskQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (
                (e.metaKey || e.ctrlKey) &&
                e.key === "Enter" &&
                !ask.isStreaming &&
                askQuestion.trim()
              ) {
                e.preventDefault();
                handleAsk();
              }
            }}
            disabled={ask.isStreaming}
            rows={3}
          />
          <p className="text-xs text-muted-foreground">
            Press Ctrl+Enter to submit
          </p>
        </div>

        {/* Models Display */}
        {!hasEmbeddingModel ? (
          <div className="flex items-center gap-2 p-3 text-sm text-amber-600 dark:text-amber-500 bg-amber-50 dark:bg-amber-950/20 rounded-md">
            <AlertCircle className="h-4 w-4" />
            <span>
              No embedding model configured. Please set one in Settings.
            </span>
          </div>
        ) : (
          <>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-xs text-muted-foreground">
                  {customModels
                    ? "Using custom models"
                    : "Using default models"}
                </Label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowAdvancedModels(true)}
                  disabled={ask.isStreaming}
                  className="h-auto py-1 px-2"
                >
                  <Settings className="h-3 w-3 mr-1" />
                  Advanced
                </Button>
              </div>
              <div className="flex gap-2 text-xs flex-wrap">
                <Badge variant="secondary">
                  Strategy:{" "}
                  {resolveModelName(
                    customModels?.strategy || modelDefaults?.default_chat_model,
                  )}
                </Badge>
                <Badge variant="secondary">
                  Answer:{" "}
                  {resolveModelName(
                    customModels?.answer || modelDefaults?.default_chat_model,
                  )}
                </Badge>
                <Badge variant="secondary">
                  Final:{" "}
                  {resolveModelName(
                    customModels?.finalAnswer ||
                      modelDefaults?.default_chat_model,
                  )}
                </Badge>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-2">
              <Button
                onClick={handleAsk}
                disabled={ask.isStreaming || !askQuestion.trim()}
                className="flex-1 min-w-0"
              >
                {ask.isStreaming ? (
                  <>
                    <LoadingSpinner size="sm" className="mr-2" />
                    <span className="truncate">Processing...</span>
                  </>
                ) : (
                  "Ask"
                )}
              </Button>

              {ask.finalAnswer && (
                <Button
                  variant="outline"
                  onClick={() => setShowSaveDialog(true)}
                  className="flex-1 min-w-0"
                >
                  <Save className="h-4 w-4 mr-2 flex-shrink-0" />
                  <span className="truncate">Save to Notebooks</span>
                </Button>
              )}
            </div>
          </>
        )}

        {/* Error Display */}
        {ask.error && (
          <div className="flex items-center gap-2 p-3 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/20 rounded-md">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span>{ask.error}</span>
          </div>
        )}

        {/* Streaming Response */}
        <StreamingResponse
          isStreaming={ask.isStreaming}
          strategy={ask.strategy}
          answers={ask.answers}
          finalAnswer={ask.finalAnswer}
        />

        {/* Advanced Models Dialog */}
        <AdvancedModelsDialog
          open={showAdvancedModels}
          onOpenChange={setShowAdvancedModels}
          defaultModels={{
            strategy:
              customModels?.strategy ||
              modelDefaults?.default_chat_model ||
              "",
            answer:
              customModels?.answer || modelDefaults?.default_chat_model || "",
            finalAnswer:
              customModels?.finalAnswer ||
              modelDefaults?.default_chat_model ||
              "",
          }}
          onSave={setCustomModels}
        />

        {/* Save to Notebooks Dialog */}
        {ask.finalAnswer && (
          <SaveToNotebooksDialog
            open={showSaveDialog}
            onOpenChange={setShowSaveDialog}
            question={askQuestion}
            answer={ask.finalAnswer}
          />
        )}
      </CardContent>
    </Card>
  );
}
