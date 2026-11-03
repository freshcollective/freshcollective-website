/**
 * Classifying Gathering Series and their occurrences for Creator Studio.
 *
 * The lifecycle itself is decided by the server — see
 * `backend/app/services/series_lifecycle.py`, which derives it at read
 * time from the stored status and the dates and writes nothing. The
 * list endpoint takes `?scope=upcoming|archive`, mirroring the events
 * endpoint, so the filtering rule lives in one place.
 *
 * What is here is presentation, plus the one question the server
 * cannot answer for a list it is not looking at: whether a Gathering
 * in the standalone list is really an occurrence of something else.
 */

// The lifecycle union lives with the other API shapes, so there is one
// declaration of what the server can send.
export type { SeriesLifecycle } from '@/types/platform'

const LABELS: Record<string, string> = {
  draft: 'Draft',
  scheduled: 'Scheduled',
  running: 'Running',
  completed: 'Completed',
  archived: 'Archived',
  // The stored statuses, for a caller that has no lifecycle.
  published: 'Published',
}

/** The pill's wording. Falls back to the raw value rather than blank. */
export function seriesLifecycleLabel(value: string | null | undefined): string {
  if (!value) return 'Series'
  return LABELS[value] ?? value
}

/**
 * The pill's colours, reusing the palette the Series band established:
 * teal for current, grey for put away, gold for not yet live.
 */
export function seriesLifecycleStyle(
  value: string | null | undefined,
): { background: string; color: string } {
  switch (value) {
    case 'running':
    case 'published':
      return { background: 'rgba(56,160,158,0.10)', color: '#0f766e' }
    case 'scheduled':
      return { background: 'rgba(56,160,158,0.06)', color: '#0f766e' }
    case 'archived':
    case 'completed':
      return { background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.55)' }
    default:
      // Draft, and anything unrecognised.
      return { background: 'rgba(214,177,63,0.14)', color: '#8a6a1f' }
  }
}

/** The fields the occurrence question is decided from. */
export interface PossibleOccurrence {
  series_id?: string | null
  recurrence_series_id?: string | null
}

/**
 * Whether a Gathering should be listed as a standalone Gathering.
 *
 * Two different relationships, and only one of them hides a row.
 *
 * `series_id` is membership of a real `EventSeries`. Those occurrences
 * are reachable through the Series card, so listing them again — a
 * term of thirty sessions appearing as thirty unrelated Gatherings —
 * is the duplication worth removing.
 *
 * `recurrence_series_id` is only the tag a bulk create stamps on rows
 * made together. **A bulk create with no Series chosen stamps that tag
 * and creates no `EventSeries` row at all**, so those occurrences have
 * no Series page to be reached through. Hiding them would not
 * de-duplicate anything; it would make them unreachable in Creator
 * Studio. So they stay listed, and the grouping they deserve is a
 * separate piece of work.
 */
export function isStandaloneGathering(event: PossibleOccurrence): boolean {
  return !event.series_id
}

/** Split a list into what belongs under "Standalone Gatherings". */
export function standaloneGatherings<T extends PossibleOccurrence>(
  events: readonly T[],
): T[] {
  return events.filter(isStandaloneGathering)
}

/** How many of a list are occurrences reachable through a Series. */
export function seriesOccurrenceCount(
  events: readonly PossibleOccurrence[],
): number {
  return events.filter((e) => !isStandaloneGathering(e)).length
}
