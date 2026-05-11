"use client";

import { useRouter } from "next/navigation";
import {
  Activity,
  BarChart3,
  MessageCircleQuestion,
  Mic,
  Shield,
  Users,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type AdminSection =
  | "overview"
  | "ask"
  | "podcasts"
  | "users"
  | "permissions"
  | "audit";

interface AdminNavBarProps {
  active: AdminSection;
  /**
   * When provided (i.e. on the admin page itself), section changes for tabs
   * that live on the admin page are forwarded to the parent so it can update
   * its tab state. ``"podcasts"`` always navigates because it is its own
   * route.
   */
  onSectionChange?: (section: AdminSection) => void;
  className?: string;
}

export function AdminNavBar({
  active,
  onSectionChange,
  className,
}: AdminNavBarProps) {
  const router = useRouter();

  const handleChange = (value: string) => {
    const section = value as AdminSection;
    if (section === "podcasts") {
      router.push("/podcasts");
      return;
    }
    if (onSectionChange) {
      onSectionChange(section);
      return;
    }
    router.push(`/admin?tab=${section}`);
  };

  return (
    <Tabs
      value={active}
      onValueChange={handleChange}
      className={cn("w-full", className)}
    >
      <TabsList className="grid w-full grid-cols-2 sm:grid-cols-6 mb-6 sm:mb-8">
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
        <TabsTrigger value="permissions" className="gap-2">
          <Shield className="h-4 w-4" />
          <span className="hidden sm:inline">Permissions</span>
        </TabsTrigger>
        <TabsTrigger value="audit" className="gap-2">
          <Activity className="h-4 w-4" />
          <span className="hidden sm:inline">Audit Logs</span>
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
}
