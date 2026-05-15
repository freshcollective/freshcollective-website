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

      {/* ── Page intro banner ── TODO: hero background matches collective page dark ocean style */}
      <div
        className="px-6 py-10 md:px-10 md:py-14"
        style={{
          background:
            'radial-gradient(rgba(66,199,198,0.08) 1px, transparent 1px), ' +
            'radial-gradient(ellipse at 88% 25%, rgba(66,199,198,0.30), transparent 50%), ' +
            'radial-gradient(ellipse at 12% 78%, rgba(56,160,158,0.18), transparent 45%), ' +
            'linear-gradient(135deg, #071824 0%, #073B3A 50%, #0F5E5C 100%)',
          backgroundSize: '22px 22px, auto, auto, auto',
        }}
      >
        <Container>
          <div
            className="mb-4 h-[2px] w-8"
            style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
          />
          <h1
            className="font-serif text-3xl md:text-4xl"
            style={{ color: '#FFFFFF' }}
          >
            Explore collectives
          </h1>
          <p
            className="mt-2 text-[15px] leading-relaxed"
            style={{ color: 'rgba(255,255,255,0.70)' }}
          >
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
