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
              Gatherings
            </span>
          </h2>
          <p className="text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.72)' }}>
            Live sessions, workshops and movement practice. Book the sessions that suit you, or message Lindsey and she can lock in your regular slot.
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
              style={{ borderColor: 'rgba(56,160,158,0.25)', background: 'rgba(56,160,158,0.04)' }}
            >
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <p className="text-[13px] font-semibold text-teal-700">
                    {pass.option_name ?? 'Your pass'}
                  </p>
                  <p className="mt-0.5 text-[12px] text-slate-500">
                    {pass.credits_per_week ? `${pass.credits_per_week} session${pass.credits_per_week !== 1 ? 's' : ''} per week` : 'Active'}
                    {validUntil && ` · valid until ${validUntil}`}
                  </p>
                </div>
                <span
                  className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                  style={{ background: 'rgba(56,160,158,0.12)', color: '#0f766e' }}
                >
                  Active
                </span>
              </div>
              {total !== null && (
                <div>
                  <div className="space-y-1 mb-2">
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-slate-500">Sessions included</span>
                      <span className="font-semibold text-navy-900">{total}</span>
                    </div>
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-slate-500">Booked</span>
                      <span className="font-semibold text-navy-900">{pass.used_credits}</span>
                    </div>
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-slate-500">Available to book</span>
                      <span className={`font-semibold ${remaining > 0 ? 'text-teal-700' : 'text-slate-400'}`}>{remaining}</span>
                    </div>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-teal-100">
                    <div
                      className="h-full rounded-full bg-teal-500"
                      style={{ width: `${total > 0 ? Math.round((pass.used_credits / total) * 100) : 0}%` }}
                    />
                  </div>
                  {exhausted ? (
                    <p className="mt-2 text-[12px] leading-relaxed text-slate-500">
                      All included sessions are booked for this term. Message Lindsey if you need help changing a session.
                    </p>
                  ) : (
                    <p className="mt-2 text-[12px] leading-relaxed" style={{ color: 'rgba(56,160,158,0.80)' }}>
                      Book sessions below, or message Lindsey and she can lock in your regular slot.
                    </p>
                  )}
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
