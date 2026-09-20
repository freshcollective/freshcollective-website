/**
 * Where a Collective card sends the person who clicks it.
 *
 * One rule, shared by every public discovery surface, because two
 * surfaces disagreeing about the same person is exactly how this went
 * wrong before: Explore stopped resolving membership in June 2026 and
 * sent members to the joining page for months, while the dashboard —
 * which kept its membership lookup — sent the same people into the
 * Collective.
 *
 *   member            → /spaces/{slug}         the Collective Home
 *   signed-in visitor → /spaces/{slug}/about   the page that explains it
 *   signed out        → /spaces/{slug}/about   same, and it is public
 *
 * Membership is the only key — not whether someone is signed in, and
 * not their platform role. The destination is safe even when the
 * caller is wrong, because ``/spaces/{slug}`` redirects non-members to
 * ``/about`` itself; this decides whether a member takes one hop or
 * two, and whether a stranger is offered a door or a wall.
 *
 * Deep links are none of this function's business. A Gathering, a
 * Series or a Pathway link is a destination in its own right, not a
 * doorway into a Collective, and passes through untouched.
 */

export interface CollectiveDestinationSpace {
  slug: string
  /** False for placeholder cards that stand in for Collectives that
   *  do not exist yet; those invite a signup rather than a visit. */
  isReal: boolean
}

export function collectiveCardHref(
  space: CollectiveDestinationSpace,
  isJoined: boolean,
): string {
  if (!space.isReal) return '/signup'
  return isJoined ? `/spaces/${space.slug}` : `/spaces/${space.slug}/about`
}

/** Active memberships → the slug set the surfaces compare against.
 *  Creator-owned Collectives arrive in this list already, normalised
 *  by ``/api/auth/me/memberships``, so an owner with no membership row
 *  is treated as joined without a special case here. */
export function activeJoinedSlugs(
  memberships: { space_slug: string; status?: string }[],
): string[] {
  return memberships
    .filter((m) => m.status === 'active')
    .map((m) => m.space_slug)
}
