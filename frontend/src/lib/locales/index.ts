import { enUS } from "./en-US";
import { ptPT } from "./pt-PT";
import { frFR } from "./fr-FR";

export const resources = {
  "en-US": { translation: enUS },
  "pt-PT": { translation: ptPT },
  "fr-FR": { translation: frFR },
} as const;

export type TranslationKeys = typeof enUS;

export type LanguageCode = "en-US" | "pt-PT" | "fr-FR";

export type Language = {
  code: LanguageCode;
  label: string;
};

export const languages: Language[] = [
  { code: "en-US", label: "English" },
  { code: "pt-PT", label: "Português" },
  { code: "fr-FR", label: "Français" },
];

export { enUS, ptPT, frFR };
