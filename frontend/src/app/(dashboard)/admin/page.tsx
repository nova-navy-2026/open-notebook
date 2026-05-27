"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { StatusDashboard } from "@/components/admin/StatusDashboard";
import { RoleManagementComponent } from "@/components/admin/RoleManagementComponent";
import { UserCreationDialog } from "@/components/admin/UserCreationDialog";
import { AuditLogViewer } from "@/components/admin/AuditLogViewer";
import { ProtectedRouteGuard } from "@/lib/hooks/use-authorization";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Users,
  Activity,
  BarChart3,
  MessageCircleQuestion,
  AlertCircle,
  Settings,
  Save,
  Mic,
} from "lucide-react";
import { useAsk } from "@/lib/hooks/use-ask";
import { useModelDefaults, useModels } from "@/lib/hooks/use-models";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { StreamingResponse } from "@/components/search/StreamingResponse";
import { AdvancedModelsDialog } from "@/components/search/AdvancedModelsDialog";
import { SaveToNotebooksDialog } from "@/components/search/SaveToNotebooksDialog";

export default function AdminDashboardPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeTab, setActiveTab] = useState("overview");

  // Ask state
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

  // Set active tab based on query parameter
  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (
      tabParam &&
      ["overview", "ask", "users", "audit"].includes(tabParam)
    ) {
      setActiveTab(tabParam);
    }
  }, [searchParams]);

  // Handle tab change - update URL. Podcasts is a separate route, so
  // navigate there instead of switching tab state.
  const handleTabChange = (tabValue: string) => {
    if (tabValue === "podcasts") {
      router.push("/podcasts");
      return;
    }
    setActiveTab(tabValue);
    router.push(`/admin?tab=${tabValue}`);
  };

  return (
    <ProtectedRouteGuard requiredRole="admin">
      <div className="w-full h-full flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="app-page-wide py-6 sm:py-8">
            <div className="mb-8">
              <h1 className="text-4xl font-bold">Admin Dashboard</h1>
              <p className="text-muted-foreground mt-2">
                Manage system, monitor health, and configure access
              </p>
            </div>

            <Tabs
              value={activeTab}
              onValueChange={handleTabChange}
              className="w-full"
            >
              <TabsList className="grid w-full grid-cols-2 sm:grid-cols-5 mb-6 sm:mb-8">
                <TabsTrigger value="overview" className="gap-2">
                  <BarChart3 className="h-4 w-4" />
                  <span className="hidden sm:inline">Overview</span>
                </TabsTrigger>
                <TabsTrigger value="ask" className="gap-2">
                  <MessageCircleQuestion className="h-4 w-4" />
                  <span className="hidden sm:inline">Ask</span>
                </TabsTrigger>
                <TabsTrigger value="podcasts" className="gap-2">
                  <Mic className="h-4 w-4" />
                  <span className="hidden sm:inline">Podcasts</span>
                </TabsTrigger>
                <TabsTrigger value="users" className="gap-2">
                  <Users className="h-4 w-4" />
                  <span className="hidden sm:inline">Users & Roles</span>
                </TabsTrigger>
                <TabsTrigger value="audit" className="gap-2">
                  <Activity className="h-4 w-4" />
                  <span className="hidden sm:inline">Audit Logs</span>
                </TabsTrigger>
              </TabsList>

              {/* Overview Tab */}
              <TabsContent value="overview" className="space-y-6">
                <StatusDashboard />

                {/* Quick Actions */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
                  <Card
                    className="cursor-pointer hover:shadow-lg transition-shadow"
                    onClick={() => setActiveTab("users")}
                  >
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-base">
                          Users & Roles
                        </CardTitle>
                        <Users className="h-5 w-5 text-blue-600" />
                      </div>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">
                        Manage users and assign roles
                      </p>
                    </CardContent>
                  </Card>

                  <Card
                    className="cursor-pointer hover:shadow-lg transition-shadow"
                    onClick={() => setActiveTab("audit")}
                  >
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-base">Audit Logs</CardTitle>
                        <Activity className="h-5 w-5 text-orange-600" />
                      </div>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">
                        Review system activities
                      </p>
                    </CardContent>
                  </Card>

                  <Card
                    className="cursor-pointer hover:shadow-lg transition-shadow"
                    onClick={() => router.push("/podcasts")}
                  >
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-base">Podcasts</CardTitle>
                        <Mic className="h-5 w-5 text-purple-600" />
                      </div>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">
                        Generate and manage podcast episodes
                      </p>
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>

              {/* Ask Tab */}
              <TabsContent value="ask" className="space-y-6">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg flex items-center gap-2">
                      <MessageCircleQuestion className="h-5 w-5" />
                      Ask Your Knowledge Base
                    </CardTitle>
                    <p className="text-sm text-muted-foreground">
                      Ask questions and get AI-powered answers from your sources
                      and notes.
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
                          No embedding model configured. Please set one in
                          Settings.
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
                                customModels?.strategy ||
                                  modelDefaults?.default_chat_model,
                              )}
                            </Badge>
                            <Badge variant="secondary">
                              Answer:{" "}
                              {resolveModelName(
                                customModels?.answer ||
                                  modelDefaults?.default_chat_model,
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
                              <span className="truncate">
                                Save to Notebooks
                              </span>
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
                          customModels?.answer ||
                          modelDefaults?.default_chat_model ||
                          "",
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
              </TabsContent>

              {/* Users & Roles Tab */}
              <TabsContent value="users" className="space-y-6">
                <div>
                  <div className="mb-6 flex items-center justify-between">
                    <div>
                      <h2 className="text-3xl font-bold">
                        User & Permissions Management
                      </h2>
                      <p className="text-muted-foreground mt-2">
                        Manage users, roles, and granular permissions
                      </p>
                    </div>
                    <UserCreationDialog
                      onUserCreated={() => setRefreshKey((k) => k + 1)}
                    />
                  </div>

                  <div className="space-y-6">
                    <RoleManagementComponent key={refreshKey} />
                  </div>
                </div>
              </TabsContent>

              {/* Audit Logs Tab */}
              <TabsContent value="audit" className="space-y-6">
                <div>
                  <h2 className="text-3xl font-bold mb-2">Audit Logs</h2>
                  <p className="text-muted-foreground mb-6">
                    Monitor system activities and user actions
                  </p>
                  <AuditLogViewer />
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </div>
    </ProtectedRouteGuard>
  );
}
