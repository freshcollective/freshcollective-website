import { cookies } from 'next/headers'
import SiteShell from '@/components/layout/SiteShell'
import { getPublicSpaces } from '@/lib/serverApi'
import { SESSION_COOKIE } from '@/lib/session'
import ExploreCollectivesExperience from '@/components/explore/ExploreCollectivesExperience'
import { toSpaceWithMeta } from '@/components/explore/spaceMeta'
import type { PublicSpaceCard } from '@/types/platform'

export default async function SpacesPage() {
  const [apiSpaces, cookieStore] = await Promise.all([
    getPublicSpaces(),
    cookies(),
  ])

  const isLoggedIn = !!cookieStore.get(SESSION_COOKIE)
  const spaces = (apiSpaces as PublicSpaceCard[]).map(toSpaceWithMeta)

  return (
    <SiteShell>
      <ExploreCollectivesExperience
        spaces={spaces}
        joinedSlugs={[]}
        isLoggedIn={isLoggedIn}
      />
    </SiteShell>
  )
}
