import Link from 'next/link'
import Container from '@/components/layout/Container'
import { getPublicSpaces, getMyMemberships } from '@/lib/serverApi'
import ExploreCollectivesExperience from '@/components/explore/ExploreCollectivesExperience'
import { toSpaceWithMeta } from '@/components/explore/spaceMeta'
import type { PublicSpaceCard, SpaceMembership } from '@/types/platform'

export default async function ExploreCollectivesPage() {
  const [apiSpaces, memberships]: [PublicSpaceCard[], SpaceMembership[]] = await Promise.all([
    getPublicSpaces(),
    getMyMemberships(),
  ])

  const joinedSlugs = memberships
    .filter((m) => m.status === 'active')
    .map((m) => m.space_slug)

  const spaces = apiSpaces.map(toSpaceWithMeta)

  return (
    <div className="flex min-h-screen flex-col bg-background">

      {/* ── Top navigation bar ── */}
      <header
        className="border-b border-border bg-surface py-3.5"
        style={{ borderTop: '2px solid #38A09E' }}
      >
        <Container className="flex items-center justify-between">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 text-sm text-slate-500 transition-colors hover:text-navy-900"
          >
            ← Dashboard
          </Link>
          <span className="font-serif text-xl text-navy-900">Fresh Collective</span>
          <span className="w-24" />
        </Container>
      </header>

      <ExploreCollectivesExperience
        spaces={spaces}
        joinedSlugs={joinedSlugs}
        isLoggedIn
      />

    </div>
  )
}
