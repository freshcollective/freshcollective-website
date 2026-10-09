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

// ---------------------------------------------------------------------------
// Waiting for access to arrive after a purchase
// ---------------------------------------------------------------------------
//
// The AccessPass is created by webhook-driven fulfilment, not by the
// redirect back from Stripe — ``purchase_fulfilment`` writes it when
// the payment event arrives. So a member can land on this page with
// ``?checkout=success`` a second or two before they have access, and
// for the weekly-payment setup flow the gap can be longer.
//
// What must never happen in that window is the one thing the page used
// to do: fall through to "Ways to join" and offer to sell them the term
// they have just bought. So the window has its own state, it waits, and
// it says so.

/** Long enough to be gentle on the API, short enough to feel live. */
export const ACCESS_POLL_INTERVAL_MS = 3000

/** Two minutes. Past this, waiting silently stops being honest. */
export const ACCESS_POLL_MAX_ATTEMPTS = 40

export type AccessWaitPhase = 'confirming' | 'slow' | 'timed_out'

/**
 * Where the wait has got to.
 *
 * Three phases rather than two, because "this is taking a moment" and
 * "this has taken two minutes" call for different things to be said,
 * and neither of them is a purchase button.
 */
export function accessWaitPhase(attempt: number): AccessWaitPhase {
  if (attempt >= ACCESS_POLL_MAX_ATTEMPTS) return 'timed_out'
  if (attempt > 5) return 'slow'
  return 'confirming'
}

export interface AccessWaitCopy {
  heading: string
  body: string
  /** True once the member should be told to act rather than wait. */
  showReload: boolean
}

/**
 * What to say while access is being set up.
 *
 * Every line is written on the assumption that the member has paid —
 * because they have. None of them suggests paying again, and the
 * longest wait still ends with reassurance plus something to do,
 * rather than an apology and a dead end.
 */
export function accessWaitCopy(phase: AccessWaitPhase): AccessWaitCopy {
  if (phase === 'timed_out') {
    return {
      heading: 'Your payment went through',
      body:
        'Your access is still being set up, which occasionally takes a ' +
        'few minutes. You do not need to pay again. Reload this page, ' +
        'and if your access still is not here, let us know and we will ' +
        'sort it out.',
      showReload: true,
    }
  }
  if (phase === 'slow') {
    return {
      heading: 'Confirming your payment',
      body:
        'This is taking a little longer than usual. Your payment has ' +
        'gone through — we are waiting for it to be confirmed, and your ' +
        'sessions will appear here as soon as it is.',
      showReload: false,
    }
  }
  return {
    heading: 'Confirming your payment',
    body:
      'One moment — as soon as this is confirmed you can choose the ' +
      'sessions you usually come to and reserve them all at once.',
    showReload: false,
  }
}
