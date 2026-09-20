import SiteShell from '@/components/layout/SiteShell'
import { getViewerCollectives } from '@/lib/joinedCollectives'
import { getPublicSpaces } from '@/lib/serverApi'
import ExploreCollectivesExperience from '@/components/explore/ExploreCollectivesExperience'
import { toSpaceWithMeta } from '@/components/explore/spaceMeta'
import type { PublicSpaceCard } from '@/types/platform'

/**
 * Explore Collectives.
 *
 * Public: anyone can browse, signed in or not. What membership
 * changes is where a card *goes* — a member is taken into the
 * Collective Home, everyone else to the public About page — plus the
 * Joined badge, the joined-first ordering and the "Your collectives"
 * grouping, all of which read the same set.
 *
 * ``getJoinedSlugs`` makes no request when there is no session
 * cookie, so public browsing stays exactly as cheap as it was. The
 * page is already dynamic (it reads cookies), so nothing about how it
 * renders changes either.
 */
export default async function SpacesPage() {
  const [apiSpaces, viewer] = await Promise.all([
    getPublicSpaces(),
    getViewerCollectives(),
  ])

  const { isLoggedIn, joinedSlugs } = viewer
  const spaces = (apiSpaces as PublicSpaceCard[]).map(toSpaceWithMeta)

  return (
    <SiteShell>
      <ExploreCollectivesExperience
        spaces={spaces}
        joinedSlugs={joinedSlugs}
        isLoggedIn={isLoggedIn}
      />
    </SiteShell>
  )
}
