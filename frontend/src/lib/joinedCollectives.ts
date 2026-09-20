import { cookies } from 'next/headers'

import { activeJoinedSlugs } from '@/lib/collectiveDestination'
import { getMyMemberships } from '@/lib/serverApi'
import { SESSION_COOKIE } from '@/lib/session'
import type { SpaceMembership } from '@/types/platform'

/**
 * Which Collectives the viewer is already inside, for public
 * discovery surfaces.
 *
 * Every surface that shows a Collective card has to answer the same
 * question — does this person already belong here, so should the card
 * take them to the Collective Home rather than the public About page —
 * and the answer has to be reached the same way each time, or two
 * surfaces disagree about the same person.
 *
 * The signed-out path is the reason this exists as a helper rather
 * than two inline fetches. Explore lost membership entirely in June
 * 2026 (commit 0fee92c) while fixing a real signed-out problem: cards
 * pointed at ``/spaces/{slug}``, which then redirected to the
 * auth-guarded ``/community``, so a logged-out visitor clicking a
 * Collective landed on the sign-in page. The fix removed the
 * membership lookup for everyone rather than skipping it for the
 * signed-out, and the signed-in behaviour never came back. The
 * destination is safe for both audiences now — ``/spaces/{slug}``
 * renders the Home for members and redirects everyone else to
 * ``/about`` — so the only thing still worth preserving from that
 * commit is its good half: **a signed-out visitor triggers no
 * membership request at all.** That is what the cookie check below is
 * for, and there is a test that fails if it is removed.
 *
 * Soft on failure. ``getMyMemberships`` already returns ``[]`` when
 * the API is unreachable or the session has expired, so a wobble
 * degrades to "nobody is a member" — every card points at the public
 * About page, which is correct for a stranger and merely one click
 * long for a member.
 */
export interface ViewerCollectives {
  /** Whether there is a session at all. Distinct from having
   *  memberships: a signed-in visitor who has joined nothing is still
   *  signed in, and surfaces that greet people must not confuse the
   *  two. */
  isLoggedIn: boolean
  /** Slugs of Collectives the viewer is an active member of, creator-
   *  owned ones included. */
  joinedSlugs: string[]
}

export async function getViewerCollectives(): Promise<ViewerCollectives> {
  const cookieStore = await cookies()
  if (!cookieStore.get(SESSION_COOKIE)) {
    return { isLoggedIn: false, joinedSlugs: [] }
  }

  const memberships = (await getMyMemberships()) as SpaceMembership[]
  return {
    isLoggedIn: true,
    joinedSlugs: activeJoinedSlugs(memberships),
  }
}
