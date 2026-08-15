import { getSpace, getSpaceMembers, getSpacePathways, getMe } from '@/lib/serverApi'
import PathwayCard from '@/components/spaces/PathwayCard'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type { MemberProfile, PathwaySummary, SpaceResponse, UserProfile } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpacePathwaysPage({ params }: Props) {
  const { slug } = await params
  const [pathways, space, members, user]: [PathwaySummary[], SpaceResponse | null, MemberProfile[], UserProfile | null] = await Promise.all([
    getSpacePathways(slug),
    getSpace(slug),
    getSpaceMembers(slug),
    getMe(),
  ])
  const isAuthenticated = user !== null

  const active = pathways.filter((p) => p.status === 'active')
  const soon = pathways.filter((p) => p.status === 'coming_soon')

  // Authoritative counts from the space detail endpoint. The
  // /api/spaces/{slug}/members list is privacy-filtered for
  // learner-role viewers (hides learners when
  // show_member_directory=False), so ``members.filter(...).length``
  // would silently render "0 members" in the sidebar for every
  // learner. Sidebar/stats must consume space.learner_count /
  // space.leader_count instead.
  const memberCount = space?.learner_count ?? 0
  const leaderCount = space?.leader_count ?? 0

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">

      {/* ── Main column ── */}
      <div className="min-w-0">

        {/* Intro card */}
        <div
          className="mb-8 overflow-hidden rounded-2xl px-7 py-7"
          style={{
            background: '#071824',
            border: '1px solid rgba(66,199,198,0.10)',
            boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
          }}
        >
          <div
            className="mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
          />
          <h2 className="mb-2 leading-snug">
            <span
              className="inline-block text-2xl font-semibold"
              style={{
                background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              Pathways
            </span>
          </h2>
          <p className="text-[14px] leading-relaxed" style={{ color: '#FFFFFF' }}>
            Choose your next step and continue your journey.
          </p>
        </div>

        {active.length === 0 && soon.length === 0 ? (
          <div
            className="rounded-2xl border bg-white px-7 py-12 text-center"
            style={{ borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.20))' }}
          >
            <p className="font-serif text-lg text-navy-800">No pathways yet.</p>
            <p className="mt-1.5 text-sm text-black">
              Pathways will appear here once they are published.
            </p>
          </div>
        ) : (
          <>
            {active.length > 0 && (
              <div className="mb-10 grid gap-5 sm:grid-cols-2">
                {active.map((pathway) => (
                  <PathwayCard key={pathway.id} pathway={pathway} spaceSlug={slug} isAuthenticated={isAuthenticated} />
                ))}
              </div>
            )}

            {soon.length > 0 && (
              <div>
                <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                  Coming Soon
                </p>
                <div className="grid gap-5 sm:grid-cols-2">
                  {soon.map((pathway) => (
                    <PathwayCard key={pathway.id} pathway={pathway} spaceSlug={slug} isAuthenticated={isAuthenticated} />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Right sidebar (desktop only) ── */}
      <aside className="hidden lg:block">
        <div className="sticky top-6">
          <CollectiveSidebarPanel
            space={space}
            memberCount={memberCount}
            leaderCount={leaderCount}
          />
        </div>
      </aside>

    </div>
  )
}
