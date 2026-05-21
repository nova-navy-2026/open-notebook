/**
 * Centralised date/time formatting helpers.
 *
 * All timestamps shown to the user are formatted using the
 * **European Portuguese** locale (`pt-PT`) and the **Europe/Lisbon**
 * timezone so that users see times in Portuguese-mainland local time
 * regardless of the browser's own locale or timezone.
 *
 * The input ``date`` may be either a ``Date`` instance, an ISO-8601 string
 * (e.g. ``"2026-05-21T12:34:56+00:00"``) or any value accepted by the
 * ``Date`` constructor. ``null`` / ``undefined`` / invalid values render
 * as an empty string so callers can use these helpers directly in JSX.
 */

const LOCALE = 'pt-PT'
const TIME_ZONE = 'Europe/Lisbon'

type DateInput = Date | string | number | null | undefined

function toDate(input: DateInput): Date | null {
  if (input === null || input === undefined || input === '') return null
  const d = input instanceof Date ? input : new Date(input)
  if (Number.isNaN(d.getTime())) return null
  return d
}

/** Format as date + time, e.g. "21/05/2026, 13:34:56". */
export function formatDateTime(input: DateInput): string {
  const d = toDate(input)
  if (!d) return ''
  return d.toLocaleString(LOCALE, { timeZone: TIME_ZONE })
}

/** Format as date only, e.g. "21/05/2026". */
export function formatDate(input: DateInput): string {
  const d = toDate(input)
  if (!d) return ''
  return d.toLocaleDateString(LOCALE, { timeZone: TIME_ZONE })
}

/** Format as time only, e.g. "13:34:56". */
export function formatTime(input: DateInput): string {
  const d = toDate(input)
  if (!d) return ''
  return d.toLocaleTimeString(LOCALE, { timeZone: TIME_ZONE })
}

/** Filename-safe timestamp in Europe/Lisbon, e.g. "2026-05-21T13-34-56". */
export function formatTimestampForFilename(input: DateInput = new Date()): string {
  const d = toDate(input)
  if (!d) return ''
  // sv-SE renders ISO-ish "YYYY-MM-DD HH:MM:SS"; swap separators for file safety.
  return d
    .toLocaleString('sv-SE', { timeZone: TIME_ZONE, hour12: false })
    .replace(' ', 'T')
    .replace(/:/g, '-')
}
