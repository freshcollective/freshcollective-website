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


// ---------------------------------------------------------------------------
// Creator-only Collectives
// ---------------------------------------------------------------------------
//
// World Builders is the platform's own Collective for Fresh Collective
// creators. Its membership is not chosen: the backend grants it from
// creator eligibility and reconciles it on every authenticated request
// (``services.creator_eligibility``), and the ordinary join endpoint
// answers 403 for it unconditionally.
//
// Two consequences shape everything below.
//
// **There is no Join action, for anybody.** An eligible creator is
// already a member by the time any page renders for them, so the only
// two states that exist are "inside" and "not a creator". A "Join"
// button would have nothing to call.
//
// **Membership IS the eligibility signal.** Because the grant is
// derived from eligibility, an active membership means eligible and
// the absence of one means not currently eligible. So the card needs
// no new "am I an eligible creator?" request — ``isJoined``, which
// every discovery surface already resolves, answers it.
//
// The one state membership cannot distinguish is somebody whose
// creator access lapsed: suspension pauses the membership and
// cancellation removes it, so they are not joined, but they are not a
// prospective creator either and must not be invited to become one.
// ``isCreator`` — the platform role from the viewer's own profile —
// separates them.

export interface CollectiveCardViewer {
  /** An active membership of this Collective. */
  isJoined: boolean
  /** Whether there is a session at all. */
  isLoggedIn: boolean
  /** Platform role is ``creator``. Says nothing about whether that
   *  access is currently in good standing — which is the point: held
   *  together with ``isJoined``, it tells a lapsed creator apart from
   *  somebody who has never been one. */
  isCreator: boolean
}

export interface CollectiveCardAction {
  label: string
  href: string
}

/** Copy, in one place so the card and its tests cannot drift. */
export const CREATOR_ONLY_BADGE = 'For Creators Only'
/** The About page's own call to action, not the card's. Kept here with
 *  the rest of the creator-only vocabulary so the wording has one home;
 *  ``publicCollectiveAbout`` re-exports what the page renders. */
export const BECOME_A_CREATOR_LABEL = 'Explore Becoming a Creator →'
export const BECOME_A_CREATOR_HREF = '/for-creators'
export const CREATOR_STATUS_LABEL = 'Check your creator status →'
export const CREATOR_STATUS_HREF = '/settings/membership'

/**
 * What a Collective card's button says, and where it goes.
 *
 * Ordinary Collectives keep exactly the behaviour they had — the
 * two-state label and :func:`collectiveCardHref`, which this
 * delegates to rather than restating.
 */
export function collectiveCardAction(
  space: CollectiveDestinationSpace & { name?: string; creator_only?: boolean },
  viewer: CollectiveCardViewer,
): CollectiveCardAction {
  const href = collectiveCardHref(space, viewer.isJoined)

  // A placeholder card invites a signup whatever else is true.
  if (!space.isReal) return { label: 'Explore →', href }

  if (space.creator_only) {
    // Named from the Collective rather than hardcoded, so the rule
    // reads as a rule — "Enter World Builders →" is what this
    // produces for the one Collective that has the flag today.
    if (viewer.isJoined) {
      return { label: `Enter ${space.name ?? 'Collective'} →`, href }
    }
    // Held creator status, not currently in good standing. Sent to
    // their own account rather than to the invitation to become
    // something they already are.
    if (viewer.isCreator) {
      return { label: CREATOR_STATUS_LABEL, href: CREATOR_STATUS_HREF }
    }
    // Everybody else, signed in or not: the Collective's own public
    // About page, like any other non-member card.
    //
    // This used to go straight to ``/for-creators``, correctly at the
    // time — the About page answered 401 to an anonymous caller, so it
    // would have been a dead end. It is public and indexable now, and
    // it is the better first stop: it explains what World Builders is
    // before asking anybody to become a creator, and it carries
    // ``Explore Becoming a Creator →`` itself. So the journey is
    //
    //   Explore Collectives → World Builders About → For Creators
    //
    // and this card is the first hop rather than a shortcut past the
    // middle one. ``collectiveCardHref`` already resolves a non-member
    // to ``/spaces/{slug}/about``, so there is nothing special to
    // compute — only the label differs from an ordinary card, and it
    // does not: "Explore →" is exactly right here.
    return { label: 'Explore →', href }
  }

  return { label: viewer.isJoined ? 'Continue →' : 'Explore →', href }
}
