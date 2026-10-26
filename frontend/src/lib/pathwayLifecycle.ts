/**
 * Which lifecycle actions a Pathway offers, and what the page says
 * when the API declines one.
 *
 * Extracted so the decisions are testable without a browser, and so
 * the gallery cannot drift from the server. Every rule here mirrors
 * one in ``backend/app/services/pathway_deletion.py`` or
 * ``pathway_access.py``; the server remains the authority, and this
 * only decides what to put on screen.
 *
 * The messages
 * ------------
 * The page used to answer every failure with "Could not delete this
 * pathway. Please try again." That is the worst possible response to
 * the only failure that actually happens: the API refuses with a 409
 * and a sentence naming the record it is protecting — a member's
 * entitlement, their progress, a Payment Option elsewhere that
 * includes this pathway. "Try again" invites the creator to repeat an
 * action that can never succeed, and says nothing about what to do
 * instead. It is also what left the reporter of FC-API-D unable to
 * tell a refusal from a crash.
 *
 * So the server's ``detail`` is shown verbatim. Those sentences are
 * written for a creator to read, and keeping a second copy of them
 * here would guarantee the two drift. The generic lines survive only
 * for the cases with nothing to show: a network failure, or a
 * response that is not JSON.
 */

export type PathwayLifecycleStatus =
  | 'draft'
  | 'active'
  | 'coming_soon'
  | 'archived'

/** Shown when a failure carries nothing more specific. */
export const GENERIC_DELETE_ERROR =
  'Could not delete this pathway. Please try again.'
export const GENERIC_ARCHIVE_ERROR =
  'Could not archive this pathway. Please try again.'
export const GENERIC_RESTORE_ERROR =
  'Could not restore this pathway. Please try again.'

/**
 * Pick the message for a failed lifecycle action.
 *
 * ``body`` is whatever came back from ``res.json()`` — deliberately
 * typed ``unknown``, because a proxy error page and an empty body are
 * both realistic and neither has a ``detail``. A FastAPI validation
 * error puts a *list* there, which must never be rendered as a
 * sentence.
 */
export function actionErrorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return fallback
}

/**
 * Whether a pathway in this status can be permanently deleted.
 *
 * Mirrors ``pathway_deletion.DELETABLE_STATUS``, and is why the
 * confirmation dialog offers no destructive button on a pathway the
 * API will decline. Note that a draft is only *eligible* — the server
 * still refuses one that was ever live or that anybody holds.
 */
export function isDeletableStatus(status: string): boolean {
  return status === 'draft'
}

/** Anything not already archived can be archived. */
export function isArchivableStatus(status: string): boolean {
  return status !== 'archived'
}

/** Only an archived pathway can be restored. */
export function isRestorableStatus(status: string): boolean {
  return status === 'archived'
}

/**
 * Restore returns a pathway to **Draft**, never straight to Live.
 *
 * The creator decides when it goes back in front of members; a silent
 * re-publish is not ours to assume. It also means restoring is always
 * safe to press — nothing becomes visible until they choose to publish.
 */
export const RESTORED_STATUS = 'draft'


// ---------------------------------------------------------------------------
// Confirmation copy
// ---------------------------------------------------------------------------
//
// Plain strings rather than JSX so the wording can be asserted
// directly. It was previously inline in the dialog, which meant the
// only way to test it was to scrape the component source — and a
// source scrape cannot tell the copy apart from a comment *about* the
// copy, which is exactly how a check like that gives a false pass.

/**
 * What archiving a pathway does, in the order a creator needs it.
 *
 * Every claim here was checked against the doors that can actually
 * sell a pathway, because the first draft said archiving meant it
 * "can no longer be bought" and that was too strong:
 *
 * | Door                                 | Archived pathway       |
 * |--------------------------------------|------------------------|
 * | ``POST /api/checkout``               | refused when every     |
 * |                                      | grant the option       |
 * |                                      | carries is an archived |
 * |                                      | pathway — i.e. the     |
 * |                                      | pathway's own option,  |
 * |                                      | and a collective-level |
 * |                                      | option granting        |
 * |                                      | nothing else           |
 * | ``POST /api/checkout/pathway``       | refused — any          |
 * |                                      | non-active status      |
 * | ``POST /api/checkout/gathering-      | still sells; its       |
 * | series``                             | option may carry a     |
 * |                                      | bundled pathway grant  |
 *
 * So "on its own" is the accurate promise, and the bundle is named
 * rather than glossed over. A bundle keeps selling on purpose —
 * refusing it would withdraw access to the pathways, series and
 * offerings that are still on offer. See
 * ``backend/app/services/pathway_commerce.unsellable_reason``.
 */
export const ARCHIVE_CONFIRM_PARAGRAPHS: readonly string[] = [
  'It will stop appearing in public listings and for members browsing '
  + 'your pathways, and nobody new can buy it on its own.',
  'Everyone who already has access keeps it — purchases, manual grants '
  + 'and passes all still open it, and their progress and reflections '
  + 'stay exactly as they are.',
  'One thing to know: if this pathway is part of a bundle that\u2019s '
  + 'still on sale, people who buy that bundle will still get access to '
  + 'it. You can change that by editing what the bundle includes.',
  'You can restore this pathway at any time.',
]

/**
 * What deleting a draft pathway does.
 *
 * The middle paragraph is the important one: the server refuses rather
 * than cascading, so the creator is told that pressing the button on a
 * pathway somebody holds is safe — it will be declined, not obeyed.
 */
export const DELETE_CONFIRM_PARAGRAPHS: readonly string[] = [
  'This will permanently remove the pathway and everything you have '
  + 'written in it.',
  'If anyone holds access, has enrolled, has recorded progress, or if a '
  + 'Payment Option elsewhere includes this pathway, the deletion will '
  + 'be declined and nothing will change.',
  'Otherwise this action cannot be undone.',
]

/** Shown if a pathway stops being a draft under an open menu. */
export const NOT_DELETABLE_PARAGRAPHS: readonly string[] = [
  'Only a draft pathway can be permanently deleted.',
  'Archive it instead, or set it back to Draft in its settings first.',
]
