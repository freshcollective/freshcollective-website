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

  const joinedSlugs = memberships
    .filter((m) => m.status === 'active')
    .map((m) => m.space_slug)

  return (
    <div className="flex min-h-screen flex-col bg-background">

      {/* ── Top navigation bar (matches dashboard) ── */}
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
          <span className="w-24" />
        </Container>
      </header>

      {/* ── Page intro banner ── */}
      <div
        className="border-b border-border px-6 py-8 md:px-10"
        style={{
          background: 'linear-gradient(135deg, #EAF7F7 0%, #F0FBFA 55%, #FAFAF8 100%)',
        }}
      >
        <Container>
          <div
            className="mb-3 h-[2px] w-8"
            style={{ background: 'linear-gradient(90deg, #38A09E 0%, transparent 100%)' }}
          />
          <h1 className="font-serif text-3xl text-navy-900 md:text-4xl">
            Explore collectives
          </h1>
          <p className="mt-2 text-[15px] leading-relaxed text-slate-500">
            Find guided spaces for learning, practice, conversation, and change.
          </p>
        </Container>
      </div>

      <main className="flex-1 py-10">
        <Container>
          <ExploreClient spaces={spaces} joinedSlugs={joinedSlugs} />
        </Container>
      </main>
    </div>
  )
}
