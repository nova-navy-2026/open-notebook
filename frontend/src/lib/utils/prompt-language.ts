// Maps an app UI locale code to a human-readable English language name that we
// pass to the chat backend as a *secondary* preference for the reply language.
// The primary rule (handled in the prompt) is always to answer in the language
// of the user's own message; this only applies when that is ambiguous.
const LANGUAGE_NAMES: Record<string, string> = {
  "en-US": "English",
  "pt-PT": "European Portuguese (pt-PT)",
  "fr-FR": "French",
  "it-IT": "Italian",
  "zh-CN": "Simplified Chinese",
  "zh-TW": "Traditional Chinese",
  "ja-JP": "Japanese",
  "ru-RU": "Russian",
  "bn-IN": "Bengali",
};

export function promptLanguageLabel(localeCode: string | undefined): string | undefined {
  if (!localeCode) return undefined;
  if (LANGUAGE_NAMES[localeCode]) return LANGUAGE_NAMES[localeCode];
  // Fall back to a base-language match (e.g. "pt-BR" → Portuguese variant).
  const base = localeCode.split("-")[0];
  const match = Object.keys(LANGUAGE_NAMES).find((code) => code.startsWith(base + "-"));
  return match ? LANGUAGE_NAMES[match] : undefined;
}
