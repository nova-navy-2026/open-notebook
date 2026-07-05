// Persists the app's main scroll position across a page navigation so a
// "Go back" action can return the user to where they were (e.g. research
// history list -> report page -> back to the same scroll offset). Session
// storage (not the navigation store) since this is a one-shot, per-key
// handoff read exactly once by the page that navigates back.
const SCROLL_CONTAINER_ID = "app-scroll-container";

export function saveScrollPosition(key: string) {
  const el = document.getElementById(SCROLL_CONTAINER_ID);
  if (!el) return;
  try {
    sessionStorage.setItem(`scroll:${key}`, String(el.scrollTop));
  } catch {
    // sessionStorage unavailable (private mode, etc.) — skip restore
  }
}

/** Reads and clears the saved position so it's only ever applied once. */
export function consumeScrollPosition(key: string): number | null {
  try {
    const raw = sessionStorage.getItem(`scroll:${key}`);
    if (raw == null) return null;
    sessionStorage.removeItem(`scroll:${key}`);
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}
