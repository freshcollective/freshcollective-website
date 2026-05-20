// TODO: COLLECTIVE_TIME_ZONE should come from collective settings, not a hardcoded constant.
export const COLLECTIVE_TIME_ZONE = 'Australia/Melbourne'

/**
 * "YYYY-MM-DD" in collective local time — used as a stable calendar placement key.
 * en-CA locale produces ISO date format natively.
 */
export function gatheringDateKey(iso: string): string {
  return new Date(iso).toLocaleDateString('en-CA', { timeZone: COLLECTIVE_TIME_ZONE })
}

/** Date key for today in collective local time. */
export function todayGatheringKey(): string {
  return gatheringDateKey(new Date().toISOString())
}

/** "10:00 AEST" or "10:00 AEDT" — local time with auto DST abbreviation. */
export function formatGatheringTime(iso: string): string {
  const d = new Date(iso)
  const parts = new Intl.DateTimeFormat('en-AU', {
    timeZone: COLLECTIVE_TIME_ZONE,
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
export function formatGatheringTimeShort(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: COLLECTIVE_TIME_ZONE,
  })
}

/** { day: "28", month: "MAY", time: "10:00 AEST" } */
export function formatGatheringDate(iso: string): { day: string; month: string; time: string } {
  const d = new Date(iso)
  const day   = d.toLocaleDateString('en-GB', { day: '2-digit',  timeZone: COLLECTIVE_TIME_ZONE })
  const month = d.toLocaleDateString('en-GB', { month: 'short', timeZone: COLLECTIVE_TIME_ZONE }).toUpperCase()
  return { day, month, time: formatGatheringTime(iso) }
}

/** "Thursday, 28 May 2026" in collective local time. */
export function formatGatheringFullDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: COLLECTIVE_TIME_ZONE,
  })
}

/** "Thursday, 28 May" label for mobile calendar day groups. */
export function formatGatheringMobileDayLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: COLLECTIVE_TIME_ZONE,
  })
}
