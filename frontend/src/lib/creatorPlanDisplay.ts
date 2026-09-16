/**
 * Creator-facing plan-name mapping.
 *
 * Internal / admin surfaces use the DB slug's canonical name — e.g.
 * ``pro``'s DB name is ``Pro``. Creator-facing surfaces (Creator
 * Studio Billing, Account → Plan) present the public marketing
 * label instead — ``Creator Portfolio`` — matching the copy on the
 * /for-creators marketing page.
 *
 * Kept slug-keyed (not name-keyed) so a future rename of the DB
 * ``name`` field via admin plan CRUD does not silently change the
 * creator-facing label.
 */

export function creatorFacingPlanName(
  slug: string | null | undefined,
  fallbackName: string,
): string {
  if (slug === 'pro') return 'Creator Portfolio'
  return fallbackName
}
