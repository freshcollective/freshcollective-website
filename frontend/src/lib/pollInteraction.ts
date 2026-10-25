/**
 * When a poll option is still something a member can act on.
 *
 * This exists because conflating two different questions is what made
 * polls unvotable. ``PollRow`` asked only "should results be shown?"
 * and, when the answer was yes, returned a static ``<div>`` — no
 * handler, no button, nothing to tap. But the server answers
 * ``show_results`` true in three situations:
 *
 *     show_results = show_results_before_vote OR user_has_voted OR is_closed
 *
 * and only the last of those means voting is over. So:
 *
 *   * a poll created with "show results before voting" rendered as
 *     results from the outset and could never be voted in at all;
 *   * after voting, every poll became read-only, so a member could not
 *     change their mind — which both the API (replace-wholesale votes)
 *     and the UI's own "Update vote" button were built to allow.
 *
 * The two questions are therefore kept apart here:
 *
 *   ``showsResults``  — do we draw bars and counts?
 *   ``isInteractive`` — does a tap still do something?
 *
 * They are independent. A poll can show results *and* accept votes;
 * that is the normal state of an open poll somebody has already voted
 * in, and of any poll configured to show results early.
 */

export interface PollInteractionState {
  /** Server's single answer on result visibility. */
  show_results: boolean
  /** Server's answer on whether the poll's closing time has passed. */
  is_closed: boolean
}

/** Draw bars and counts? Purely the server's decision. */
export function showsResults(poll: PollInteractionState): boolean {
  return poll.show_results
}

/**
 * Does tapping an option still do anything?
 *
 * Only two things stop it: the poll has closed, or a request is already
 * in flight. Notably **not** whether results are visible, and **not**
 * whether this member has already voted — changing a vote is supported
 * by the API and is the point of the "Update vote" affordance.
 */
export function isInteractive(
  poll: PollInteractionState,
  busy: boolean,
): boolean {
  return !poll.is_closed && !busy
}

/**
 * What a single option row should render, as one value so the component
 * cannot drift from the rule.
 *
 *   ``bar-interactive`` — results visible, still votable
 *   ``bar-static``      — results visible, poll closed or busy
 *   ``choice``          — results hidden, still votable
 *   ``choice-static``   — results hidden and not votable (busy mid-vote
 *                         on a poll that hides results)
 */
export type PollRowMode =
  | 'bar-interactive'
  | 'bar-static'
  | 'choice'
  | 'choice-static'

export function pollRowMode(
  poll: PollInteractionState,
  busy: boolean,
): PollRowMode {
  const live = isInteractive(poll, busy)
  if (showsResults(poll)) return live ? 'bar-interactive' : 'bar-static'
  return live ? 'choice' : 'choice-static'
}

/** Whether a row in this mode responds to a tap. */
export function modeIsTappable(mode: PollRowMode): boolean {
  return mode === 'bar-interactive' || mode === 'choice'
}

/** Whether a row in this mode draws the vote-share bar. */
export function modeShowsBar(mode: PollRowMode): boolean {
  return mode === 'bar-interactive' || mode === 'bar-static'
}

/**
 * Should a "Clear vote" control be offered?
 *
 * One rule for both poll kinds. Multiple choice has always had this;
 * single choice had no way to retract at all, even though the API reads
 * an empty ``option_ids`` as "remove my vote" and nothing about a
 * single-choice poll makes retraction different.
 *
 * Two conditions, both necessary:
 *
 *   * there is a vote to clear — otherwise the control would do
 *     nothing and only add noise to an unanswered poll;
 *   * the poll is still open — a closed poll's record stands, so the
 *     control must not be offered at all rather than offered and
 *     refused.
 *
 * Deliberately **not** gated on ``busy``: the control stays rendered
 * mid-request and is disabled instead, so it does not disappear under
 * the member's finger. That matches how the Cast/Update button already
 * behaves.
 */
export function showsClearVote(poll: {
  is_closed: boolean
  user_has_voted: boolean
}): boolean {
  return !poll.is_closed && poll.user_has_voted
}


/**
 * The next selection after tapping ``optionId``.
 *
 * Single choice replaces; multiple choice toggles. Returned rather than
 * mutated so the submit path and the local-state path cannot disagree
 * about what a tap meant.
 */
export function nextSelection(
  current: readonly string[],
  optionId: string,
  allowMultiple: boolean,
): string[] {
  if (!allowMultiple) return [optionId]
  return current.includes(optionId)
    ? current.filter((id) => id !== optionId)
    : [...current, optionId]
}
