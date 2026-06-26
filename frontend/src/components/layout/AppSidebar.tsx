"use client";

import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname, useSearchParams, useRouter } from "next/navigation";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/hooks/use-auth";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useSidebarStore } from "@/lib/stores/sidebar-store";
import { useCreateDialogs } from "@/lib/hooks/use-create-dialogs";
import { useRBAC } from "@/lib/contexts/rbac-context";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ThemeToggle } from "@/components/common/ThemeToggle";
import { LanguageToggle } from "@/components/common/LanguageToggle";
import { UserProfileMenu } from "@/components/auth/UserProfileMenu";
import { TranslationKeys } from "@/lib/locales";
import { useTranslation } from "@/lib/hooks/use-translation";
import { useTheme } from "@/components/providers/ThemeProvider";
import { Separator } from "@/components/ui/separator";
import { SettingsModal } from "@/components/layout/SettingsModal";
import {
  Book,
  Search,
  Mic,
  Bot,
  Shuffle,
  Settings,
  ChevronLeft,
  Menu,
  FileText,
  Plus,
  Wrench,
  LayoutDashboard,
  FlaskConical,
  MessageCircle,
  MessageCircleQuestion,
  Image as ImageIcon,
  Video,
  Captions,
} from "lucide-react";

type NavItem = {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
};

type NavSection = {
  title: string;
  items: NavItem[];
};

const getNavigation = (t: TranslationKeys): { main: NavSection[]; admin: NavSection[] } => ({
  main: [
    {
      title: t.navigation.collect,
      items: [{ name: t.navigation.sources, href: "/sources", icon: FileText }],
    },
    {
      title: t.navigation.process,
      items: [
        { name: t.navigation.search ?? "Search", href: "/search", icon: Search },
        { name: t.navigation.chat ?? "Chat", href: "/chat", icon: MessageCircle },
        { name: t.navigation.notebooks, href: "/notebooks", icon: Book },
      ],
    },
    {
      title: t.navigation.create,
      items: [
        { name: t.navigation.research ?? "Research", href: "/research", icon: FlaskConical },
        { name: t.navigation.imageAnalysis ?? "Image Analysis", href: "/vision/image-analysis", icon: ImageIcon },
        { name: t.navigation.videoAnalysis ?? "Video Analysis", href: "/vision/video-tracking", icon: Video },
      ],
    },
    {
      title: t.navigation.audio ?? "Audio",
      items: [
        { name: t.navigation.transcription ?? "Transcription", href: "/transcription", icon: Captions },
      ],
    },
  ],
  admin: [
    {
      title: t.navigation.manage,
      items: [
        { name: t.navigation.models, href: "/settings/api-keys", icon: Bot },
        { name: t.navigation.transformations, href: "/transformations", icon: Shuffle },
        { name: t.navigation.settings, href: "/settings", icon: Settings },
        { name: t.navigation.advanced, href: "/advanced", icon: Wrench },
      ],
    },
    {
      title: "Admin",
      items: [
        { name: "Dashboard", href: "/admin?tab=overview", icon: LayoutDashboard },
        { name: "Ask", href: "/admin?tab=ask", icon: MessageCircleQuestion },
        { name: t.navigation.podcasts, href: "/podcasts", icon: Mic },
        { name: "Users & Roles", href: "/admin?tab=users", icon: Settings },
        { name: "Audit Logs", href: "/admin?tab=audit", icon: FileText },
      ],
    },
  ],
});

type CreateTarget =
  | "chat"
  | "notebook"
  | "source"
  | "research"
  | "transcription"
  | "image-analysis"
  | "video-analysis";

export function AppSidebar() {
  const { t } = useTranslation();
  const { isAdmin } = useRBAC();
  const { resolvedTheme } = useTheme();
  const { main: mainNavigation } = getNavigation(t);
  const logoSrc =
    resolvedTheme === "dark" ? "/logo_dark.png" : "/logo_light.png";
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { logout } = useAuth();
  const { user } = useAuthStore();
  const { isCollapsed, toggleCollapse } = useSidebarStore();
  const { openSourceDialog, openNotebookDialog, openPodcastDialog } =
    useCreateDialogs();
  void openSourceDialog;
  void openPodcastDialog;

  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const handleCreateSelection = (target: CreateTarget) => {
    setCreateMenuOpen(false);

    switch (target) {
      case "chat":
        router.push("/chat");
        break;
      case "notebook":
        openNotebookDialog();
        break;
      case "source":
        openSourceDialog();
        break;
      case "research":
        router.push("/research");
        break;
      case "transcription":
        router.push("/transcription");
        break;
      case "image-analysis":
        router.push("/vision/image-analysis");
        break;
      case "video-analysis":
        router.push("/vision/video-tracking");
        break;
    }
  };

  const getBasePath = (path: string) => path.split("?")[0];
  const getQueryParams = (path: string) => {
    const parts = path.split("?");
    return parts.length > 1 ? new URLSearchParams(parts[1]) : null;
  };

  const renderNavItem = (item: NavItem, section: NavSection) => {
    const itemBasePath = getBasePath(item.href);
    const pathnameBase = getBasePath(pathname || "");
    const itemParams = getQueryParams(item.href);

    let isActive: boolean;

    if (itemParams) {
      const itemTab = itemParams.get("tab");
      const currentTab = searchParams.get("tab");
      isActive = itemBasePath === pathnameBase && itemTab === currentTab;
    } else {
      const matches = section.items.filter((i) => {
        const iBasePath = getBasePath(i.href);
        return (
          iBasePath === pathnameBase ||
          pathnameBase?.startsWith(iBasePath + "/")
        );
      });
      const bestMatch =
        matches.length > 0
          ? matches.sort((a, b) => b.href.length - a.href.length)[0]
          : null;
      isActive = bestMatch ? getBasePath(bestMatch.href) === itemBasePath : false;
    }

    const button = (
      <Button
        variant={isActive ? "secondary" : "ghost"}
        className={cn(
          "w-full gap-3 text-sidebar-foreground sidebar-menu-item",
          isActive && "bg-sidebar-accent text-sidebar-accent-foreground",
          isCollapsed ? "justify-center px-2" : "justify-start",
        )}
      >
        <item.icon className="h-4 w-4" />
        {!isCollapsed && <span>{item.name}</span>}
      </Button>
    );

    if (isCollapsed) {
      return (
        <Tooltip key={item.name}>
          <TooltipTrigger asChild>
            <Link href={item.href} scroll={false}>
              {button}
            </Link>
          </TooltipTrigger>
          <TooltipContent side="right">{item.name}</TooltipContent>
        </Tooltip>
      );
    }

    return (
      <Link key={item.name} href={item.href} scroll={false}>
        {button}
      </Link>
    );
  };

  return (
    <TooltipProvider delayDuration={0}>
      <div
        className={cn(
          "app-sidebar flex h-full flex-col bg-sidebar border-sidebar-border border-r transition-all duration-300",
          isCollapsed ? "w-16" : "w-64",
        )}
      >
        <div
          className={cn(
            "flex h-16 items-center group",
            isCollapsed ? "justify-center px-2" : "justify-between px-4",
          )}
        >
          {isCollapsed ? (
            <div className="relative flex items-center justify-center w-full">
              <Image
                src={logoSrc}
                alt="Marinheiro de Silício"
                width={32}
                height={32}
                style={{ width: "auto", height: "auto" }}
                className="transition-opacity group-hover:opacity-0"
              />
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleCollapse}
                className="absolute text-sidebar-foreground hover:bg-sidebar-accent opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Menu className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Image
                  src={logoSrc}
                  alt={t.common.appName}
                  width={32}
                  height={32}
                  style={{ width: "auto", height: "auto" }}
                />
                <span className="text-base font-medium text-sidebar-foreground">
                  {t.common.appName}
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleCollapse}
                className="text-sidebar-foreground hover:bg-sidebar-accent"
                data-testid="sidebar-toggle"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>

        <nav
          className={cn(
            "flex-1 flex flex-col pt-1 pb-2 overflow-hidden",
            isCollapsed ? "px-2" : "px-3",
          )}
        >
          {/* Create button */}
          <div className={cn("mb-2", isCollapsed ? "px-0" : "px-3")}>
            <DropdownMenu
              open={createMenuOpen}
              onOpenChange={setCreateMenuOpen}
            >
              {isCollapsed ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <DropdownMenuTrigger asChild>
                      <Button
                        onClick={() => setCreateMenuOpen(true)}
                        variant="default"
                        size="sm"
                        className="w-full justify-center px-2 bg-primary hover:bg-primary/90 text-primary-foreground border-0"
                        aria-label={t.common.create}
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                  </TooltipTrigger>
                  <TooltipContent side="right">
                    {t.common.create}
                  </TooltipContent>
                </Tooltip>
              ) : (
                <DropdownMenuTrigger asChild>
                  <Button
                    onClick={() => setCreateMenuOpen(true)}
                    variant="default"
                    size="sm"
                    className="w-full justify-start bg-primary hover:bg-primary/90 text-primary-foreground border-0"
                  >
                    <Plus className="h-4 w-4 mr-2" />
                    {t.common.create}
                  </Button>
                </DropdownMenuTrigger>
              )}

              <DropdownMenuContent
                align={isCollapsed ? "end" : "start"}
                side={isCollapsed ? "right" : "bottom"}
                className="w-48"
              >
                {/* Order mirrors the sidebar menu: Sources, Chat, Workspaces,
                    Research, Image, Video, Transcription. */}
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault();
                    handleCreateSelection("source");
                  }}
                  className="gap-2"
                >
                  <FileText className="h-4 w-4" />
                  {t.common.newSource ?? "New Source"}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault();
                    handleCreateSelection("chat");
                  }}
                  className="gap-2"
                >
                  <MessageCircle className="h-4 w-4" />
                  {t.navigation.chat ?? t.common.chat ?? "Chat"}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault();
                    handleCreateSelection("notebook");
                  }}
                  className="gap-2"
                >
                  <Book className="h-4 w-4" />
                  {t.common.notebook}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault();
                    handleCreateSelection("research");
                  }}
                  className="gap-2"
                >
                  <FlaskConical className="h-4 w-4" />
                  {t.navigation.research ?? "Deep Research"}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault();
                    handleCreateSelection("image-analysis");
                  }}
                  className="gap-2"
                >
                  <ImageIcon className="h-4 w-4" />
                  {t.navigation.imageAnalysis ?? "Image Analysis"}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault();
                    handleCreateSelection("video-analysis");
                  }}
                  className="gap-2"
                >
                  <Video className="h-4 w-4" />
                  {t.navigation.videoAnalysis ?? "Video Analysis"}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault();
                    handleCreateSelection("transcription");
                  }}
                  className="gap-2"
                >
                  <Captions className="h-4 w-4" />
                  {t.navigation.transcription ?? "Transcription"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {/* Main navigation — grouped at the top with consistent spacing */}
          <div className="flex-1 min-h-0 flex flex-col gap-5 overflow-y-auto overflow-x-hidden pt-1">
            {mainNavigation.map((section) => (
              <div key={section.title} className="space-y-1">
                {!isCollapsed && (
                  <h3 className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/50">
                    {section.title}
                  </h3>
                )}
                {section.items.map((item) => renderNavItem(item, section))}
              </div>
            ))}
          </div>

          {/* Settings button — bottom of nav, admins only */}
          {isAdmin && (
            <div className="pt-2">
              <Separator className="mb-2" />
              {isCollapsed ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      className="w-full justify-center px-2 text-sidebar-foreground sidebar-menu-item"
                      onClick={() => setSettingsOpen(true)}
                      aria-label="Settings"
                    >
                      <Settings className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="right">Settings</TooltipContent>
                </Tooltip>
              ) : (
                <Button
                  variant="ghost"
                  className="w-full justify-start gap-3 text-sidebar-foreground sidebar-menu-item"
                  onClick={() => setSettingsOpen(true)}
                >
                  <Settings className="h-4 w-4" />
                  <span>Settings</span>
                </Button>
              )}
            </div>
          )}
        </nav>

        <div
          className={cn(
            "border-t border-sidebar-border py-2 px-3",
            isCollapsed ? "px-2" : "",
          )}
        >
          {isCollapsed ? (
            <div className="flex flex-col items-center">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="w-full flex justify-center">
                    <UserProfileMenu />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="right">{t.common.account}</TooltipContent>
              </Tooltip>
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <UserProfileMenu />
              {user && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex min-w-0 flex-1 flex-col leading-tight cursor-default select-none pointer-events-auto">
                      <span className="truncate text-sm font-medium text-sidebar-foreground">
                        {user.name || user.email}
                      </span>
                      {user.name && (
                        <span className="truncate text-xs text-sidebar-foreground/60">
                          {user.email}
                        </span>
                      )}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs">
                    <div className="flex flex-col gap-0.5">
                      {user.name && <span className="font-medium">{user.name}</span>}
                      <span className="text-xs">{user.email}</span>
                    </div>
                  </TooltipContent>
                </Tooltip>
              )}
              <div className="flex gap-1 shrink-0">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="w-9">
                      <ThemeToggle iconOnly />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top">{t.common.theme}</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="w-9">
                      <LanguageToggle iconOnly />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top">{t.common.language}</TooltipContent>
                </Tooltip>
              </div>
            </div>
          )}
        </div>

        <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </div>
    </TooltipProvider>
  );
}
