/**
 * Duplicating one Pathway step: where the request goes, and what to say.
 *
 * The backend does the work — it copies content blocks and step
 * resources into a new step immediately after the source, with new
 * identities throughout, and announces nothing. See
 * ``backend/app/services/pathway_step_duplication.py`` for what is and
 * is not carried, and why member activity cannot follow.
 *
 * Kept out of the editor component so the endpoint, the copy and the
 * error policy are testable without a DOM.
 */

export function stepDuplicateEndpoint(
  spaceSlug: string, pathwaySlug: string, stepSlug: string,
): string {
  return `/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}`
    + `/steps/${stepSlug}/duplicate`
}

/** The new step's own editor. */
export function stepEditorHref(pathwaySlug: string, stepSlug: string): string {
  return `/creator-studio/pathways/${pathwaySlug}/steps/${stepSlug}`
}

export const STEP_DUPLICATE_SUCCESS =
  'Step duplicated. You can now edit your new step.'

/**
 * Whether to warn before duplicating.
 *
 * A step has no draft state of its own — visibility is the Pathway's —
 * so a duplicate in a Pathway members can already open is visible to
 * them the moment it exists, carrying the original's title and
 * content. That is worth one sentence before it happens rather than a
 * surprise afterwards. A draft Pathway needs no warning.
 */
export function stepDuplicateNeedsConfirmation(
  pathwayStatus: string | null | undefined,
): boolean {
  return pathwayStatus === 'active'
}

export const STEP_DUPLICATE_LIVE_WARNING =
  'This Pathway is published, so the copy will be visible to members '
  + 'straight away — with the original’s title and content until you '
  + 'edit it.\n\nDuplicate the step now?'

/**
 * A creator-facing message for a failed duplication.
 *
 * Mirrors the policy used elsewhere in the creator editors: only the
 * statuses we raise with our own text are shown verbatim, so a bare
 * framework "Not Found" or "Internal Server Error" never reaches a
 * creator.
 */
export function stepDuplicateErrorMessage(
  status: number, detail: unknown,
): string {
  if ((status === 400 || status === 409)
      && typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (status === 403) {
    return 'You don’t have permission to duplicate steps in this Pathway.'
  }
  if (status === 404) {
    return 'That step could not be found. It may have been deleted.'
  }
  return 'The step couldn’t be duplicated. Please try again.'
}
