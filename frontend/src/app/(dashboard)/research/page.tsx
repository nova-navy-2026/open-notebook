"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ResearchGeneratePanel } from "@/components/research/ResearchGeneratePanel";
import { ResearchJobsList } from "@/components/research/ResearchJobsList";
import { useTranslation } from "@/lib/hooks/use-translation";

export default function ResearchPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState("generate");

  return (
    <div className="flex flex-col h-full overflow-y-auto px-4 md:px-6 py-6 space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">
          {t.research?.title ?? "Research"}
        </h1>
        <p className="text-muted-foreground">
          {t.research?.subtitle ??
            "Generate in-depth research reports powered by NOVA-Researcher and AMALIA AI."}
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="generate">
            {t.research?.newResearch ?? "New Research"}
          </TabsTrigger>
          <TabsTrigger value="jobs">
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
  );
}
