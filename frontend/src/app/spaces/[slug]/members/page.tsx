import { getMe, getSpace, getSpaceMembers } from '@/lib/serverApi'
import MembersView from '@/components/spaces/MembersView'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type { MemberProfile, SpaceResponse } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceMembersPage({ params }: Props) {
  const { slug } = await params
  const [me, members, space] = await Promise.all([
    getMe(),
    getSpaceMembers(slug),
    getSpace(slug) as Promise<SpaceResponse | null>,
  ])
  const typedMembers = members as MemberProfile[]

  const leaders = typedMembers.filter(
    (m) => m.space_role === 'creator' || m.space_role === 'moderator',
  )
  const learners = typedMembers.filter((m) => m.space_role === 'learner')

  const currentUserMember = me ? typedMembers.find((m) => m.id === me.id) : null
  const canInvite =
    currentUserMember?.space_role === 'creator' ||
    currentUserMember?.space_role === 'moderator'

  return (
    <div className="max-w-5xl">

      {/* ── Intro card — navy/gradient ── */}
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
        <h1 className="mb-2 leading-snug">
          <span
            className="inline-block text-2xl font-semibold"
            style={{
              background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            Members
          </span>
        </h1>
        <p className="text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.72)' }}>
          The people inside this collective — here to learn, reflect, and grow together.
        </p>
      </div>

      {/* ── Two-column layout ── */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">

        {/* ── Left: searchable member list ── */}
        <MembersView
          leaders={leaders}
          learners={learners}
          spaceSlug={slug}
          canInvite={canInvite}
        />

        {/* ── Right: banner + stats + Important panel ── */}
        <div className="lg:sticky lg:top-6">
          <CollectiveSidebarPanel
            space={space}
            memberCount={learners.length}
            leaderCount={leaders.length}
          />
        </div>

      </div>
    </div>
  )
}
