// TODO: timezone should come from collective settings passed at call sites — do not re-add a hardcoded constant here.


/**
 * Parse a server-emitted datetime string as UTC.
 *
 * Pydantic v2 serialises TZ-naive ``DateTime(timezone=False)`` columns
 * WITHOUT a ``Z`` suffix (e.g. ``"2026-10-05T07:00:00"``). Per ES2019+
 * browsers parse those strings as LOCAL time — which for our app is
 * catastrophically wrong because the storage convention is naive-UTC.
 * This helper appends a ``Z`` when there's no timezone designator so
 * every caller gets the same UTC-anchored ``Date`` regardless of what
 * the backend emitted.
 *
 * Strings that already carry a ``Z`` or a numeric offset (``+11:00``,
 * ``-05:30``) pass through unchanged.
 */
export function parseServerDatetime(iso: string): Date {
  const hasOffset = /Z$|[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasOffset ? iso : iso + 'Z')
}


/**
 * Format a stored *calendar date* as a human-readable string.
 *
 * Some fields are calendar dates, not instants — Gathering Series
 * ``starts_at`` / ``ends_at``, for example, are set from a
 * ``<input type="date">`` and stored as ``YYYY-MM-DDT00:00:00`` /
 * ``YYYY-MM-DDT23:59:59``. Passing those through the timezone-aware
 * ``parseServerDatetime`` path is wrong: 23:59:59 UTC converts to
 * 10:59 the NEXT day in Melbourne, so a Series that ends 12 Dec
 * would render as ending 13 Dec.
 *
 * This helper reads the calendar day directly from the string (first
 * ten characters, ``YYYY-MM-DD``) and formats it as a local
 * ``Date`` constructed at LOCAL midnight — no timezone conversion,
 * no rollover. Robust to strings with or without a time portion.
 *
 * Options default to ``{ day: 'numeric', month: 'short', year:
 * 'numeric' }`` (matches the Gathering Series banner style); callers
 * can override.
 */
export function formatCalendarDate(
  iso: string,
  options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' },
): string {
  const match = String(iso).slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return ''
  const [, y, m, d] = match
  // Construct a local Date at midnight — represents the calendar day
  // regardless of the viewer's timezone. Do NOT pass ``timeZone`` to
  // the formatter; that would round-trip through UTC and reintroduce
  // the bug.
  const dt = new Date(Number(y), Number(m) - 1, Number(d))
  return dt.toLocaleDateString('en-AU', options)
}


/**
 * "YYYY-MM-DD" in the given timezone — used as a stable calendar placement key.
 * en-CA locale produces ISO date format natively.
 */
export function gatheringDateKey(iso: string, timezone: string): string {
  return parseServerDatetime(iso).toLocaleDateString('en-CA', { timeZone: timezone })
}

/** Date key for today in the given timezone. */
export function todayGatheringKey(timezone: string): string {
  return gatheringDateKey(new Date().toISOString(), timezone)
}

/** "10:00 AEST" or "10:00 AEDT" — local time with auto DST abbreviation. */
export function formatGatheringTime(iso: string, timezone: string): string {
  const d = parseServerDatetime(iso)
  const parts = new Intl.DateTimeFormat('en-AU', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZoneName: 'short',
  }).formatToParts(d)
  const hour   = parts.find(p => p.type === 'hour')?.value   ?? '00'
  const minute = parts.find(p => p.type === 'minute')?.value ?? '00'
  const tz     = parts.find(p => p.type === 'timeZoneName')?.value ?? ''
  return `${hour}:${minute} ${tz}`
}

/** "10:00" without timezone label — for compact calendar chips. */
export function formatGatheringTimeShort(iso: string, timezone: string): string {
  return parseServerDatetime(iso).toLocaleTimeString('en-AU', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timezone,
  })
}

/** { day: "28", month: "MAY", time: "10:00 AEST" } */
export function formatGatheringDate(iso: string, timezone: string): { day: string; month: string; time: string } {
  const d = parseServerDatetime(iso)
  const day   = d.toLocaleDateString('en-AU', { day: '2-digit',  timeZone: timezone })
  const month = d.toLocaleDateString('en-AU', { month: 'short', timeZone: timezone }).toUpperCase()
  return { day, month, time: formatGatheringTime(iso, timezone) }
}

/** "Thursday, 28 May 2026" in the given timezone. */
export function formatGatheringFullDate(iso: string, timezone: string): string {
  return parseServerDatetime(iso).toLocaleDateString('en-AU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: timezone,
  })
}

/** "Thursday, 28 May" label for mobile calendar day groups. */
export function formatGatheringMobileDayLabel(iso: string, timezone: string): string {
  return parseServerDatetime(iso).toLocaleDateString('en-AU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: timezone,
  })
}

/** "19 Sep 2026" — compact display date, no timezone conversion. */
export function formatDisplayDate(iso: string): string {
  return parseServerDatetime(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** "19/09/2026" — numeric form / helper display date. */
export function formatNumericDate(iso: string): string {
  return parseServerDatetime(iso).toLocaleDateString('en-AU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

/**
 * Gentle countdown label for an upcoming Gathering, e.g.
 *   "Starts in 3 days"  "Tomorrow"  "Today"  "Starting now"
 *   "Live now"          "Ended"
 *
 * `endsAt` is optional; when provided we surface "Live now" during the
 * event window and "Ended" once past. When absent we assume a 60-min
 * window (matches the iCal fallback in the detail page).
 *
 * Computed at render time so a page refresh always shows fresh copy —
 * the caller (typically a server component) can call this directly,
 * or a client card can re-render on interval. Kept as a pure function.
 */
export function countdownLabel(
  startsAt: string,
  endsAt: string | null = null,
  now: Date = new Date(),
): string {
  const start = parseServerDatetime(startsAt)
  const end = endsAt ? parseServerDatetime(endsAt) : new Date(start.getTime() + 60 * 60 * 1000)

  if (now >= end) return 'Ended'
  if (now >= start) return 'Live now'

  const msUntil = start.getTime() - now.getTime()
  const minsUntil = Math.floor(msUntil / 60000)
  if (minsUntil <= 15) return 'Starting soon'

  // Day-based buckets keyed to local calendar days, not raw hours,
  // so "Tomorrow" reads correctly whether it's 23h or 26h away.
  const startDay = new Date(start.getFullYear(), start.getMonth(), start.getDate())
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const daysUntil = Math.round((startDay.getTime() - today.getTime()) / (24 * 60 * 60 * 1000))

  if (daysUntil <= 0) return 'Today'
  if (daysUntil === 1) return 'Tomorrow'
  if (daysUntil < 7)  return `Starts in ${daysUntil} days`
  if (daysUntil < 14) return 'Next week'
  const weeks = Math.round(daysUntil / 7)
  if (weeks < 5)  return `In ${weeks} weeks`
  const months = Math.round(daysUntil / 30)
  return `In ${months} month${months === 1 ? '' : 's'}`
}
