/**
 * The two derivations behind Creator Studio → Collective Overview.
 *
 * Extracted from ``app/creator-studio/home/page.tsx`` so they can be
 * tested. The page is a server component, so its logic was previously
 * unreachable by the Node test runner — which is how it kept a defect
 * that had already been fixed on a sibling page.
 *
 * That defect: the Overview fetched Gatherings UNSCOPED and filtered
 * them client-side on start time alone, with no status check. EMBODY's
 * Snapshot therefore read "31 upcoming gatherings" when 28 were active,
 * and "Next gathering" named *Test1* — a cancelled standalone whose
 * start time was merely the earliest. Both numbers came from one array,
 * so one filter was wrong in two visible places.
 *
 * The status rule now lives where it belongs: the API's
 * ``scope=upcoming``, which applies ``status == 'active'`` AND
 * not-yet-ended. Nothing here re-implements it — a second copy of a rule
 * is how the first copy drifts.
 */

import { parseServerDatetime } from './dateTime.ts'

/**
 * Gatherings in chronological order, earliest first.
 *
 * Expects a list ALREADY scoped by the API (``scope=upcoming``). The
 * caller's job is to ask for the right scope; this one only orders.
 *
 * Ordering goes through ``parseServerDatetime`` because the API emits
 * naive-UTC strings with no designator, which ES2019+ parses as local —
 * identical on a UTC host and off by the offset anywhere else.
 */
export function orderGatheringsByStart<T extends { starts_at: string }>(
  events: readonly T[],
): T[] {
  return [...events].sort(
    (a, b) =>
      parseServerDatetime(a.starts_at).getTime() -
      parseServerDatetime(b.starts_at).getTime(),
  )
}

/** The Snapshot count and the "Next gathering" moment, from one array. */
export function overviewGatherings<T extends { starts_at: string }>(
  events: readonly T[],
): { ordered: T[]; count: number; next: T | null } {
  const ordered = orderGatheringsByStart(events)
  return { ordered, count: ordered.length, next: ordered[0] ?? null }
}

/**
 * "3d ago" / "in 2h", falling back to a short date beyond a week.
 *
 * Timezone matters only for the fallback, but it matters: the date was
 * rendered from a bare ``new Date`` with no ``timeZone``, so a Saturday
 * 9 am Melbourne Gathering showed the Friday. The elapsed-time maths was
 * wrong too — a naive string parsed as local shifts the instant itself.
 *
 * Deliberately not a new formatter: it reuses ``parseServerDatetime`` and
 * the same ``{day, month}`` shape the page already rendered.
 */
export function formatMomentWhen(
  iso: string,
  timezone: string,
  now: Date = new Date(),
): string {
  if (!iso) return ''
  const then = parseServerDatetime(iso).getTime()
  if (Number.isNaN(then)) return ''

  const diff = Math.abs(now.getTime() - then)
  const past = now.getTime() > then
  const min = 60_000
  const hour = 60 * min
  const day = 24 * hour

  if (diff < min) return past ? 'just now' : 'soon'
  if (diff < hour) return past ? `${Math.floor(diff / min)}m ago` : `in ${Math.floor(diff / min)}m`
  if (diff < day) return past ? `${Math.floor(diff / hour)}h ago` : `in ${Math.floor(diff / hour)}h`
  if (diff < 7 * day) return past ? `${Math.floor(diff / day)}d ago` : `in ${Math.floor(diff / day)}d`

  return parseServerDatetime(iso).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    timeZone: timezone,
  })
}
