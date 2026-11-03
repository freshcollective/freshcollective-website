/**
 * Who may be duplicated, where the request goes, and what to say when
 * it fails.
 *
 * The backend endpoint has existed since migration 175 and does the
 * real work — it builds a new dateless draft field by field rather
 * than cloning a row, so nothing instance-specific can come with it.
 * It also refuses a Series occurrence outright. Nothing here is a
 * second implementation of any of that; this is the interface's half,
 * kept out of the components so it can be tested without a DOM.
 *
 * The eligibility rule below **mirrors** the server's refusal rather
 * than replacing it. Hiding a button is a courtesy, not a control: a
 * creator who reaches the endpoint another way still gets the 400.
 */

/** The fields eligibility is decided from. */
export interface DuplicableGathering {
  id: string
  /** Semantic membership of a Gathering Series. */
  series_id?: string | null
  /** The tag left on rows created together by a bulk recurrence. */
  recurrence_series_id?: string | null
}

/**
 * Whether Duplicate should be offered for this Gathering.
 *
 * Draft, published, completed and archived are all eligible — the
 * action copies configuration, and configuration is worth reusing
 * whatever state the original is in.
 *
 * Both kinds of series membership refuse. An occurrence takes its
 * meaning from the series it belongs to: its label, its index, the
 * pass that admits a member to all of them. A copy would either carry
 * a membership it has no claim to or be a stray wearing a series name.
 * Adding a session is a Series-level action.
 *
 * `recurrence_series_id` matters on its own. The Gatherings list
 * filters its "Standalone" section on `series_id` only, so a
 * bulk-created occurrence with no semantic Series appears there — and
 * the endpoint would refuse it.
 */
export function canDuplicateGathering(event: DuplicableGathering): boolean {
  return !event.series_id && !event.recurrence_series_id
}

/** Why the action is not being offered, for a title attribute. */
export function duplicateIneligibleReason(
  event: DuplicableGathering,
): string | null {
  if (canDuplicateGathering(event)) return null
  return 'This Gathering belongs to a series. Add a session to the series instead.'
}

export function duplicateEndpoint(spaceSlug: string, eventId: string): string {
  return `/api/creator/spaces/${spaceSlug}/events/${eventId}/duplicate`
}

/** Where the creator lands: the new draft's own editor. */
export function duplicateDraftHref(spaceSlug: string, newEventId: string): string {
  return `/creator/spaces/${spaceSlug}/events/${newEventId}`
}

/** What the creator is told when a duplicate is created. */
export const DUPLICATE_SUCCESS_MESSAGE =
  'Draft created. Set a new date and time, then publish when you’re ready.'

/**
 * A creator-facing message for a failed duplicate.
 *
 * Mirrors `friendlyApiError` in the Series editor: only 400 and 409
 * carry text we wrote, so only those are shown verbatim. A bare
 * framework "Not Found" or "Internal Server Error" never reaches a
 * creator.
 */
export function duplicateErrorMessage(
  status: number,
  detail: unknown,
): string {
  if ((status === 400 || status === 409)
      && typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (status === 403) {
    return 'You don’t have permission to duplicate this Gathering.'
  }
  if (status === 404) {
    return 'That Gathering could not be found. It may have been deleted.'
  }
  return 'The Gathering couldn’t be duplicated. Please try again.'
}
