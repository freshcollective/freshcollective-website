import { getSpace, getSpaceEvents, getSpaceMembers, getMySpaceAccess } from '@/lib/serverApi'
import GatheringsView from '@/components/spaces/GatheringsView'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type { EventSummary, MemberProfile, SpaceResponse, SpaceAccessStatus } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceEventsPage({ params }: Props) {
  const { slug } = await params
  const [space, events, members, access]: [SpaceResponse | null, EventSummary[], MemberProfile[], SpaceAccessStatus | null] = await Promise.all([
    getSpace(slug),
    getSpaceEvents(slug),
    getSpaceMembers(slug),
    getMySpaceAccess(slug),
  ])
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
