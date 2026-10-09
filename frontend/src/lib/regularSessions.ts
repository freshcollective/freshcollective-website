/**
 * "Reserve your regular sessions" — the shapes and the sentences.
 *
 * A member with a term pass for a weekly Series picks the slots that
 * are theirs — Mondays at 6, Thursdays at 6 — and every remaining
 * matching occurrence is reserved in one action.
 *
 * The pure parts live here so they can be asserted under
 * ``node --test``: the wording the member reads before confirming, and
 * the wording they read afterwards. Both are load-bearing. The whole
 * promise of this feature is that nothing is skipped quietly, and that
 * promise is kept or broken by a sentence.
 *
 * The weekly-slot labels ("Mondays — 6:00–7:00 pm") are built on the
 * backend, in the Collective's timezone, because that is where the
 * grouping happens and the two must not disagree about which sessions
 * a slot contains.
 */

export interface SchedulePattern {
  key: string
  weekday: number
  weekday_label: string
  time_label: string
  label: string
  start_time: string
  end_time: string | null
  occurrence_count: number
  already_booked_count: number
  shares_weekday: boolean
  first_starts_at: string
  last_starts_at: string
}

export interface RegularSessionsResponse {
  timezone: string
  patterns: SchedulePattern[]
  remaining_occurrence_count: number
}

export interface OccurrenceOutcome {
  event_id: string
  title: string
  starts_at: string
  ends_at: string | null
  pattern_key: string
  reason: string | null
  message: string | null
}

export interface ReservationPreview {
  timezone: string
  selected_keys: string[]
  new_reservation_count: number
  will_reserve: OccurrenceOutcome[]
  already_booked: OccurrenceOutcome[]
  unavailable: OccurrenceOutcome[]
}

export interface ReservationResult {
  timezone: string
  reserved_count: number
  reserved: OccurrenceOutcome[]
  already_booked: OccurrenceOutcome[]
  unavailable: OccurrenceOutcome[]
  changed_since_preview: OccurrenceOutcome[]
}

/** Plural-aware "session"/"sessions", because "1 sessions" reads as a bug. */
export function sessionCount(n: number): string {
  return `${n} ${n === 1 ? 'session' : 'sessions'}`
}

/**
 * The headline above the preview.
 *
 * Leads with what will happen, which is the number the member is about
 * to agree to. Says "nothing new" rather than "0 sessions" when there
 * is nothing to do — a zero presented as a quantity reads like a
 * failure rather than an already-complete state.
 */
export function previewHeadline(preview: ReservationPreview): string {
  if (preview.new_reservation_count === 0) {
    if (preview.already_booked.length > 0 && preview.unavailable.length === 0) {
      return 'You have already reserved every session in this schedule.'
    }
    return 'Nothing new to reserve in this schedule.'
  }
  return `Reserve ${sessionCount(preview.new_reservation_count)}.`
}

/**
 * The supporting lines: what else the member should know before
 * confirming. Each is only mentioned when it is true, so an ordinary
 * clean preview stays one sentence.
 */
export function previewNotes(preview: ReservationPreview): string[] {
  const notes: string[] = []
  if (preview.already_booked.length > 0) {
    notes.push(
      `${sessionCount(preview.already_booked.length)} already reserved — ` +
      `these are left as they are.`,
    )
  }
  if (preview.unavailable.length > 0) {
    notes.push(
      `${sessionCount(preview.unavailable.length)} cannot be reserved. ` +
      `They are listed below, and will be left unreserved.`,
    )
  }
  return notes
}

/** The label on the confirm button — never a bare "Confirm". */
export function confirmLabel(preview: ReservationPreview): string {
  if (preview.unavailable.length > 0 && preview.new_reservation_count > 0) {
    return `Reserve the available ${sessionCount(preview.new_reservation_count)}`
  }
  return `Reserve ${sessionCount(preview.new_reservation_count)}`
}

/**
 * What happened, after the fact.
 *
 * The case worth getting right is the one where the world moved: the
 * member agreed to twelve and got eleven. That must lead, not hide
 * behind a success message.
 */
export function resultHeadline(result: ReservationResult): string {
  const changed = result.changed_since_preview.length
  if (changed > 0 && result.reserved_count > 0) {
    return (
      `Reserved ${sessionCount(result.reserved_count)}. ` +
      `${changed} became unavailable while you were deciding.`
    )
  }
  if (changed > 0) {
    return (
      `Nothing was reserved — ${sessionCount(changed)} became ` +
      `unavailable while you were deciding.`
    )
  }
  if (result.reserved_count === 0 && result.already_booked.length > 0) {
    return 'Those sessions were already reserved.'
  }
  if (result.reserved_count === 0) {
    return 'Nothing was reserved.'
  }
  return `Reserved ${sessionCount(result.reserved_count)}.`
}

/**
 * Whether the member needs to see the detail list opened for them.
 *
 * Anything other than a clean success deserves the dates on screen
 * without a second click.
 */
export function resultNeedsAttention(result: ReservationResult): boolean {
  return (
    result.changed_since_preview.length > 0 ||
    result.unavailable.length > 0
  )
}

/**
 * The group a pattern's time label belongs in when a day carries more
 * than one slot. Returns the label alone when it is the only slot that
 * day, so the common case does not read as a disambiguation.
 */
export function patternDescription(pattern: SchedulePattern): string {
  const remaining = pattern.occurrence_count - pattern.already_booked_count
  const scope = pattern.already_booked_count > 0
    ? `${sessionCount(remaining)} to reserve · ${pattern.already_booked_count} already yours`
    : `${sessionCount(pattern.occurrence_count)} remaining`
  return scope
}
