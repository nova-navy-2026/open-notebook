"use client";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Languages } from "lucide-react";
import { useTranslation } from "@/lib/hooks/use-translation";

interface LanguageToggleProps {
  iconOnly?: boolean;
}

// French is intentionally hidden from the language picker for now. The locale
// and all its translations remain in the codebase — flip this to `true` to
// bring the option back.
const SHOW_FRENCH = false;

export function LanguageToggle({ iconOnly = false }: LanguageToggleProps) {
  const { language, setLanguage, t } = useTranslation();

  // Keep the actual language code for proper comparison
  const currentLang = language || "en-US";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant={iconOnly ? "ghost" : "outline"}
          size={iconOnly ? "icon" : "default"}
          className={
            iconOnly
              ? "h-9 w-full sidebar-menu-item"
              : "w-full justify-start gap-2 sidebar-menu-item"
          }
        >
          <Languages className="h-[1.2rem] w-[1.2rem]" />
          {!iconOnly && <span>{t.common.language}</span>}
          <span className="sr-only">{t.navigation.language}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onClick={() => setLanguage("en-US")}
          className={
            currentLang === "en-US" || currentLang.startsWith("en")
              ? "bg-accent"
              : ""
          }
        >
          <span>{t.common.english}</span>
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => setLanguage("pt-PT")}
          className={
            currentLang === "pt-PT" || currentLang.startsWith("pt")
              ? "bg-accent"
              : ""
          }
        >
          <span>{t.common.portuguese}</span>
        </DropdownMenuItem>
        {SHOW_FRENCH && (
          <DropdownMenuItem
            onClick={() => setLanguage("fr-FR")}
            className={
              currentLang === "fr-FR" || currentLang.startsWith("fr")
                ? "bg-accent"
                : ""
            }
          >
            <span>{t.common.french}</span>
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
