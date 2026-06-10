// TODO: timezone should come from collective settings passed at call sites — do not re-add a hardcoded constant here.

/**
 * "YYYY-MM-DD" in the given timezone — used as a stable calendar placement key.
 * en-CA locale produces ISO date format natively.
 */
export function gatheringDateKey(iso: string, timezone: string): string {
  return new Date(iso).toLocaleDateString('en-CA', { timeZone: timezone })
}

/** Date key for today in the given timezone. */
export function todayGatheringKey(timezone: string): string {
  return gatheringDateKey(new Date().toISOString(), timezone)
}

/** "10:00 AEST" or "10:00 AEDT" — local time with auto DST abbreviation. */
export function formatGatheringTime(iso: string, timezone: string): string {
  const d = new Date(iso)
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
  return new Date(iso).toLocaleTimeString('en-AU', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timezone,
  })
}

/** { day: "28", month: "MAY", time: "10:00 AEST" } */
export function formatGatheringDate(iso: string, timezone: string): { day: string; month: string; time: string } {
  const d = new Date(iso)
  const day   = d.toLocaleDateString('en-AU', { day: '2-digit',  timeZone: timezone })
  const month = d.toLocaleDateString('en-AU', { month: 'short', timeZone: timezone }).toUpperCase()
  return { day, month, time: formatGatheringTime(iso, timezone) }
}

/** "Thursday, 28 May 2026" in the given timezone. */
export function formatGatheringFullDate(iso: string, timezone: string): string {
  return new Date(iso).toLocaleDateString('en-AU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: timezone,
  })
}

/** "Thursday, 28 May" label for mobile calendar day groups. */
export function formatGatheringMobileDayLabel(iso: string, timezone: string): string {
  return new Date(iso).toLocaleDateString('en-AU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: timezone,
  })
}

/** "19 Sep 2026" — compact display date, no timezone conversion. */
export function formatDisplayDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** "19/09/2026" — numeric form / helper display date. */
export function formatNumericDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-AU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
