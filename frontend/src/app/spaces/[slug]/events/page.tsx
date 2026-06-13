import Link from 'next/link'
import { getSpace, getSpaceEvents, getSpaceMembers, getMySpaceAccess, getMyPasses } from '@/lib/serverApi'
import GatheringsView from '@/components/spaces/GatheringsView'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type { EventSummary, MemberProfile, SpaceResponse, SpaceAccessStatus, AccessPassSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceEventsPage({ params }: Props) {
  const { slug } = await params

  let passes: AccessPassSummary[] = []
  const [space, events, members, access] = await Promise.all([
    getSpace(slug),
    getSpaceEvents(slug),
    getSpaceMembers(slug),
    getMySpaceAccess(slug),
  ]) as [SpaceResponse | null, EventSummary[], MemberProfile[], SpaceAccessStatus | null]

  // Fetch passes for members only — non-fatal if it fails
  if (access?.is_member) {
    try { passes = await getMyPasses(slug) } catch { /* ignore */ }
  }

  const activePasses = passes.filter((p) => p.status === 'active' && p.pass_type === 'term_pass')
  const isMember = access?.is_member ?? false

  const timezone = space?.timezone ?? 'Australia/Melbourne'
  const memberCount = members.filter((m) => m.space_role === 'learner').length
  const leaderCount = members.filter((m) => m.space_role === 'creator' || m.space_role === 'moderator').length

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
              Live Gatherings
            </span>
          </h2>
          <p className="text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.72)' }}>
            Live calls, workshops, and integration sessions. These are moments to gather,
            reflect, and move through the work together.
          </p>
        </div>

        {/* ── Active term pass widget ── */}
        {activePasses.map((pass) => {
          const validUntil = pass.valid_until
            ? new Date(pass.valid_until).toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })
            : null
          const remaining = pass.remaining_credits
          const total = pass.total_credits
          return (
            <div
              key={pass.id}
              className="mb-6 rounded-2xl border p-5"
              style={{ borderColor: 'rgba(56,160,158,0.25)', background: 'rgba(56,160,158,0.04)' }}
            >
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <p className="text-[13px] font-semibold text-teal-700">
                    {pass.option_name ?? 'Term Pass'}
                  </p>
                  <p className="mt-0.5 text-[12px] text-slate-500">
                    Active{validUntil && ` · valid until ${validUntil}`}
                  </p>
                </div>
                {pass.credits_per_week && (
                  <span
                    className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                    style={{ background: 'rgba(56,160,158,0.12)', color: '#0f766e' }}
                  >
                    {pass.credits_per_week}/week
                  </span>
                )}
              </div>
              {total !== null && (
                <div className="mb-1">
                  <div className="mb-1 flex items-baseline justify-between text-[12px]">
                    <span className="text-slate-500">{remaining ?? 0} of {total} sessions remaining</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-teal-100">
                    <div
                      className="h-full rounded-full bg-teal-500"
                      style={{ width: `${total > 0 ? Math.round(((remaining ?? 0) / total) * 100) : 0}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          )
        })}

        {/* List / Calendar toggle + content */}
        <GatheringsView events={events} spaceSlug={slug} timezone={timezone} isMember={isMember} />

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
