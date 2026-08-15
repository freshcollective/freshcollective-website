import Link from 'next/link'
import {
  getSpace,
  getSpaceEvents,
  getSpaceMembers,
  getMySpaceAccess,
  getMyPasses,
  getSpaceGatheringSeries,
} from '@/lib/serverApi'
import MemberGatheringsGrid from '@/components/spaces/MemberGatheringsGrid'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type { EventSummary, MemberProfile, SpaceResponse, SpaceAccessStatus, AccessPassSummary } from '@/types/platform'

interface SeriesSummary {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  starts_at: string
  ends_at: string | null
  total_gathering_count: number
  upcoming_gathering_count: number
  has_purchasable_options: boolean
  access: { has_access: boolean; option_name: string | null }
}

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceEventsPage({ params }: Props) {
  const { slug } = await params

  let passes: AccessPassSummary[] = []
  const [space, events, pastEvents, members, access, series] = await Promise.all([
    getSpace(slug),
    getSpaceEvents(slug, 'upcoming'),
    getSpaceEvents(slug, 'archive'),
    getSpaceMembers(slug),
    getMySpaceAccess(slug),
    getSpaceGatheringSeries(slug),
  ]) as [
    SpaceResponse | null, EventSummary[], EventSummary[], MemberProfile[],
    SpaceAccessStatus | null, SeriesSummary[],
  ]

  const hasArchive = pastEvents.length > 0

  // Fetch passes for members only — non-fatal if it fails
  if (access?.is_member) {
    try { passes = await getMyPasses(slug) } catch { /* ignore */ }
  }

  const activePasses = passes.filter((p) => p.status === 'active' && p.pass_type === 'term_pass')

  // Standalone Gatherings only on the landing — Series children
  // live inside their Series page per the U1 information model.
  // (Backend already filters events cleanly; the client-side
  // filter here is deliberate insurance against Series children
  // ever slipping through the upcoming feed.)
  const standaloneEvents = events.filter((e) => !e.series_id)

  // Authoritative counts — the members list is privacy-filtered for
  // learner-role viewers (see spaces.get_space + members.list_members).
  // Sidebar must NOT derive counts from that filtered list.
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
              Gatherings
            </span>
          </h2>
          <p className="text-[14px] leading-relaxed" style={{ color: '#FFFFFF' }}>
            Upcoming ways to come together in this Collective.
          </p>
        </div>

        {/* ── Active term pass widget ── */}
        {activePasses.map((pass) => {
          const validUntil = pass.valid_until
            ? new Date(pass.valid_until).toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })
            : null
          const remaining = pass.remaining_credits ?? 0
          const total = pass.total_credits
          const exhausted = total !== null && remaining <= 0
          return (
            <div
              key={pass.id}
              className="mb-6 rounded-2xl border p-5"
              style={{
                borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.25))',
                background: 'var(--fc-accent-tint, rgba(56,160,158,0.04))',
              }}
            >
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <p className="text-[13px] font-semibold" style={{ color: 'var(--fc-accent, #0f766e)' }}>
                    {pass.option_name ?? 'Your pass'}
                  </p>
                  <p className="mt-0.5 text-[12px] text-black">
                    {pass.credits_per_week ? `${pass.credits_per_week} session${pass.credits_per_week !== 1 ? 's' : ''} per week` : 'Active'}
                    {validUntil && ` · valid until ${validUntil}`}
                  </p>
                </div>
                <span
                  className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                  style={{
                    background: 'var(--fc-accent-soft, rgba(56,160,158,0.12))',
                    color: 'var(--fc-accent, #0f766e)',
                  }}
                >
                  Active
                </span>
              </div>
              {total !== null && (
                <div>
                  <div className="space-y-1 mb-2">
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-black">Sessions included</span>
                      <span className="font-semibold text-navy-900">{total}</span>
                    </div>
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-black">Booked</span>
                      <span className="font-semibold text-navy-900">{pass.used_credits}</span>
                    </div>
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-black">Available to book</span>
                      <span
                        className="font-semibold"
                        style={{ color: remaining > 0 ? 'var(--fc-accent, #0f766e)' : '#000' }}
                      >{remaining}</span>
                    </div>
                  </div>
                  <div
                    className="h-1.5 w-full overflow-hidden rounded-full"
                    style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))' }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${total > 0 ? Math.round((pass.used_credits / total) * 100) : 0}%`,
                        background: 'var(--fc-accent, #14b8a6)',
                      }}
                    />
                  </div>
                  {exhausted ? (
                    <p className="mt-2 text-[12px] leading-relaxed text-black">
                      All included sessions are booked for this term. Message Lindsey if you need help changing a session.
                    </p>
                  ) : (
                    <p className="mt-2 text-[12px] leading-relaxed text-slate-600">
                      Book sessions below, or message Lindsey and she can lock in your regular slot.
                    </p>
                  )}
                </div>
              )}
            </div>
          )
        })}

        {/* One card per Series + one card per standalone Gathering.
            The former "GatheringsView" list/calendar toggle that
            rendered every child Event as its own top-level card is
            retired in favour of this Series-collapsed model — see
            docs/product-brief.md and the U1 M1 spec. */}
        <MemberGatheringsGrid
          spaceSlug={slug}
          series={series}
          standaloneEvents={standaloneEvents}
        />

        {hasArchive && (
          <div className="mt-8 flex justify-center">
            <Link
              href={`/spaces/${slug}/events/archive`}
              className="rounded-full px-4 py-2 text-[13px] font-medium transition-colors"
              style={{
                background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
                color: 'var(--fc-accent, #0f766e)',
              }}
            >
              View past Gatherings →
            </Link>
          </div>
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
