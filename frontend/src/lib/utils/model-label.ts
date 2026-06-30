/**
 * Display-only model label.
 *
 * The Amália model is SERVED by the vLLM endpoint under its original
 * HuggingFace name `carminho/AMALIA-9B-50-DPO` — that is the exact id we must
 * send as the `model` param (anything else 404s). But the org has since
 * rebranded to `amalia-llm`, so for the UI we relabel `carminho/` → `amalia-llm/`.
 * This NEVER changes the value sent to the backend; it's cosmetic only.
 */
export function formatModelLabel(name?: string | null): string {
  if (!name) return ''
  return name.replace(/^carminho\//, 'amalia-llm/')
}
