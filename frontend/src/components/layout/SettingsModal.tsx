"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTranslation } from "@/lib/hooks/use-translation";
import { useRBAC } from "@/lib/contexts/rbac-context";
import { cn } from "@/lib/utils";
import {
  Bot,
  Shuffle,
  Settings,
  Wrench,
  LayoutDashboard,
  MessageCircleQuestion,
  Mic,
  Users,
  Activity,
  ShieldAlert,
} from "lucide-react";

// Settings pages rendered inline inside the modal. Each page is self-contained
// (handles its own data fetching, auth guard and internal scrolling).
import ApiKeysPage from "@/app/(dashboard)/settings/api-keys/page";
import TransformationsPage from "@/app/(dashboard)/transformations/page";
import SettingsPage from "@/app/(dashboard)/settings/page";
import AdvancedPage from "@/app/(dashboard)/advanced/page";
import PodcastsPage from "@/app/(dashboard)/podcasts/page";
import { StatusDashboard } from "@/components/admin/StatusDashboard";
import { AskPanel } from "@/components/admin/AskPanel";
import { AuditLogViewer } from "@/components/admin/AuditLogViewer";
import { FlaggedContentViewer } from "@/components/admin/FlaggedContentViewer";
import { RoleManagementComponent } from "@/components/admin/RoleManagementComponent";
import { UserCreationDialog } from "@/components/admin/UserCreationDialog";

type TabId =
  | "models"
  | "transformations"
  | "settings"
  | "advanced"
  | "dashboard"
  | "ask"
  | "podcasts"
  | "users"
  | "flagged"
  | "audit";

type Tab = {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

type TabGroup = {
  title: string;
  tabs: Tab[];
};

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsModal({ open, onClose }: SettingsModalProps) {
  const { t } = useTranslation();
  const { isAdmin } = useRBAC();
  const [activeTab, setActiveTab] = useState<TabId>("models");
  const [usersRefreshKey, setUsersRefreshKey] = useState(0);

  // Reset to the first tab whenever the modal is re-opened.
  useEffect(() => {
    if (open) setActiveTab("models");
  }, [open]);

  const groups: TabGroup[] = [
    {
      title: t.navigation.manage,
      tabs: [
        { id: "models", label: t.navigation.models, icon: Bot },
        { id: "transformations", label: t.navigation.transformations, icon: Shuffle },
        { id: "settings", label: t.navigation.settings, icon: Settings },
        { id: "advanced", label: t.navigation.advanced, icon: Wrench },
      ],
    },
    ...(isAdmin
      ? [
          {
            title: "Admin",
            tabs: [
              { id: "dashboard" as TabId, label: "Dashboard", icon: LayoutDashboard },
              { id: "ask" as TabId, label: "Ask", icon: MessageCircleQuestion },
              { id: "podcasts" as TabId, label: t.navigation.podcasts, icon: Mic },
              { id: "users" as TabId, label: "Users & Roles", icon: Users },
              { id: "flagged" as TabId, label: "Flagged Content", icon: ShieldAlert },
              { id: "audit" as TabId, label: "Audit Logs", icon: Activity },
            ],
          },
        ]
      : []),
  ];

  const renderContent = () => {
    switch (activeTab) {
      case "models":
        return <ApiKeysPage />;
      case "transformations":
        return <TransformationsPage />;
      case "settings":
        return <SettingsPage />;
      case "advanced":
        return <AdvancedPage />;
      case "podcasts":
        return <PodcastsPage />;
      case "dashboard":
        return (
          <div className="flex-1 overflow-y-auto p-6">
            <StatusDashboard />
          </div>
        );
      case "ask":
        return (
          <div className="flex-1 overflow-y-auto p-6">
            <AskPanel />
          </div>
        );
      case "users":
        return (
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold">User & Permissions Management</h2>
                <p className="text-muted-foreground text-sm mt-1">
                  Manage users, roles, and granular permissions
                </p>
              </div>
              <UserCreationDialog
                onUserCreated={() => setUsersRefreshKey((k) => k + 1)}
              />
            </div>
            <RoleManagementComponent key={usersRefreshKey} />
          </div>
        );
      case "flagged":
        return (
          <div className="flex-1 overflow-y-auto p-6">
            <FlaggedContentViewer />
          </div>
        );
      case "audit":
        return (
          <div className="flex-1 overflow-y-auto p-6">
            <AuditLogViewer />
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent
        showCloseButton
        className="block max-w-6xl w-full h-[85vh] p-0 overflow-hidden gap-0 sm:max-w-6xl"
      >
        <div className="flex h-full min-h-0">
          {/* Left rail — tabs */}
          <aside className="w-56 shrink-0 border-r border-border bg-muted/30 flex flex-col">
            <div className="px-5 py-4">
              <DialogTitle className="text-base font-semibold">
                Settings
              </DialogTitle>
            </div>
            <nav className="flex-1 overflow-y-auto px-3 pb-4 space-y-4">
              {groups.map((group) => (
                <div key={group.title}>
                  <p className="mb-1 px-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {group.title}
                  </p>
                  <div className="space-y-0.5">
                    {group.tabs.map((tab) => {
                      const isActive = activeTab === tab.id;
                      return (
                        <button
                          key={tab.id}
                          onClick={() => setActiveTab(tab.id)}
                          className={cn(
                            "w-full flex items-center gap-3 px-2 py-1.5 rounded-md text-sm transition-colors cursor-pointer",
                            isActive
                              ? "bg-accent text-accent-foreground font-medium"
                              : "text-foreground hover:bg-accent/60",
                          )}
                        >
                          <tab.icon
                            className={cn(
                              "h-4 w-4 shrink-0",
                              isActive
                                ? "text-accent-foreground"
                                : "text-muted-foreground",
                            )}
                          />
                          <span className="truncate">{tab.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </nav>
          </aside>

          {/* Right pane — active page content. The pt-12 sits OUTSIDE the inner
              scroll container, so scrolled content always stops at a fixed line
              just below the modal's absolute close (X) button (top-4 + h-6 ≈ 40px). */}
          <div className="flex-1 min-w-0 flex flex-col min-h-0 bg-background pt-12">
            {renderContent()}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
