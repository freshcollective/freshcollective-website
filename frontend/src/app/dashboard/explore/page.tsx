import Link from 'next/link'
import Container from '@/components/layout/Container'
import { getPublicSpaces, getMyMemberships } from '@/lib/serverApi'
import type { PublicSpaceCard, SpaceMembership } from '@/types/platform'
import ExploreClient from './ExploreClient'

export default async function ExploreCollectivesPage() {
  const [spaces, memberships]: [PublicSpaceCard[], SpaceMembership[]] = await Promise.all([
    getPublicSpaces(),
    getMyMemberships(),
  ])

  // Slugs the user already actively belongs to
  const joinedSlugs = memberships
    .filter((m) => m.status === 'active')
    .map((m) => m.space_slug)

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header
        className="border-b border-border bg-surface py-3.5"
        style={{ borderTop: '2px solid var(--color-gold-500)' }}
      >
        <Container className="flex items-center justify-between">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 text-sm text-slate-500 transition-colors hover:text-navy-900"
          >
            ← Dashboard
          </Link>
          <span className="font-serif text-lg text-navy-900">Fresh Collective</span>
          <span className="w-24" /> {/* balance the header */}
        </Container>
      </header>

      <main className="flex-1 py-12">
        <Container>
          <div className="mb-10">
            <div className="mb-3 h-px w-6 bg-gold-500" />
            <h1 className="font-serif text-3xl text-navy-900 md:text-4xl">
              Explore collectives
            </h1>
            <p className="mt-2 text-[15px] leading-relaxed text-slate-500">
              Find guided spaces for learning, practice, conversation, and change.
            </p>
          </div>

          <ExploreClient spaces={spaces} joinedSlugs={joinedSlugs} />
        </Container>
      </main>
    </div>
  )
}
