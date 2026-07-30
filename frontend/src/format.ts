// Formatting helpers: sec/km ↔ m:ss/km, seconds → h:mm:ss, ISO week Monday
// math, weekday names from ints (0=Mon..6=Sun).

export const WEEKDAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const WEEKDAY_NAMES_FULL = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
]

/** 305 → "5:05". Returns '' for null/undefined. */
export function secToMinSec(sec: number | null | undefined): string {
  if (sec == null) return ''
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/** 305 → "5:05/km". */
export function formatPace(secPerKm: number | null | undefined): string {
  const ms = secToMinSec(secPerKm)
  return ms === '' ? '' : `${ms}/km`
}

/** "5:05" or "5:05/km" → 305. Returns null on empty/invalid input. */
export function parsePace(input: string): number | null {
  const cleaned = input.trim().replace(/\/km$/, '')
  if (cleaned === '') return null
  const match = /^(\d+):([0-5]?\d)$/.exec(cleaned)
  if (!match) return null
  return Number(match[1]) * 60 + Number(match[2])
}

/** 4523 → "1:15:23". Returns '' for null/undefined. */
export function secToHms(sec: number | null | undefined): string {
  if (sec == null) return ''
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.round(sec % 60)
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** "1:15:23" or "75:23" or "4523" → 4523. Returns null on empty/invalid. */
export function parseHms(input: string): number | null {
  const cleaned = input.trim()
  if (cleaned === '') return null
  const parts = cleaned.split(':').map(Number)
  if (parts.some((p) => Number.isNaN(p))) return null
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  if (parts.length === 1) return parts[0]
  return null
}

/** Monday of the ISO week containing `d`. */
export function mondayOf(d: Date): Date {
  const result = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const weekday = (result.getDay() + 6) % 7 // JS 0=Sun → 0=Mon
  result.setDate(result.getDate() - weekday)
  return result
}

/** The Monday after today (next week). */
export function nextMonday(): Date {
  const monday = mondayOf(new Date())
  monday.setDate(monday.getDate() + 7)
  return monday
}

/** Local date → "YYYY-MM-DD" (no timezone drift). */
export function toISODate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** "YYYY-MM-DD" → local Date (no UTC shift). */
export function fromISODate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function addDays(d: Date, days: number): Date {
  const result = new Date(d)
  result.setDate(result.getDate() + days)
  return result
}

/** "2026-05-11" → "Mon 11 May" style label. */
export function formatDateShort(iso: string): string {
  const d = fromISODate(iso)
  const weekday = WEEKDAY_NAMES[(d.getDay() + 6) % 7]
  const month = d.toLocaleString('en', { month: 'short' })
  return `${weekday} ${d.getDate()} ${month}`
}
