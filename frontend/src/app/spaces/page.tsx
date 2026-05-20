import SiteShell from '@/components/layout/SiteShell'
import { getPublicSpaces, getMyMemberships, getMe } from '@/lib/serverApi'
import ExploreCollectivesExperience from '@/components/explore/ExploreCollectivesExperience'
import { toSpaceWithMeta } from '@/components/explore/spaceMeta'
import type { PublicSpaceCard, SpaceMembership } from '@/types/platform'

export default async function SpacesPage() {
  const [apiSpaces, memberships, me]: [PublicSpaceCard[], SpaceMembership[], unknown] =
    await Promise.all([getPublicSpaces(), getMyMemberships(), getMe()])

  const spaces = apiSpaces.map(toSpaceWithMeta)

  const joinedSlugs = (memberships as SpaceMembership[])
    .filter((m) => m.status === 'active')
    .map((m) => m.space_slug)

  return (
    <SiteShell>
      <ExploreCollectivesExperience
        spaces={spaces}
        joinedSlugs={joinedSlugs}
        isLoggedIn={!!me}
      />
    </SiteShell>
  )
}
