"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ResearchGeneratePanel } from "@/components/research/ResearchGeneratePanel";
import { ResearchJobsList } from "@/components/research/ResearchJobsList";
import { useTranslation } from "@/lib/hooks/use-translation";
import { PageInfoButton } from "@/components/common/PageInfoButton";

export default function ResearchPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState("generate");

  return (
    <div className="flex flex-col">
      <div className="app-page space-y-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h1 className="text-3xl font-bold tracking-tight">
            {t.research?.title ?? "Research"}
          </h1>
          <PageInfoButton pageKey="research" />
        </div>
        <p className="text-muted-foreground">
          {t.research?.subtitle ??
            "Generate in-depth, multi-source research reports from your documents."}
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="generate" className="whitespace-nowrap">
            {t.research?.newResearch ?? "New Research"}
          </TabsTrigger>
          <TabsTrigger value="jobs" className="whitespace-nowrap">
            {t.research?.history ?? "History"}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="generate" className="mt-6">
          <ResearchGeneratePanel
            onJobStarted={() => setActiveTab("jobs")}
          />
        </TabsContent>

        <TabsContent value="jobs" className="mt-6">
          <ResearchJobsList />
        </TabsContent>
      </Tabs>
      </div>
    </div>
  );
}
