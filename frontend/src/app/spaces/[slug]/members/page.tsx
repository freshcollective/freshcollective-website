import { notFound } from 'next/navigation'
import { getMe, getSpace, getSpaceMembers } from '@/lib/serverApi'
import { requireArea } from '@/lib/areaAccess'
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

  // A Collective this viewer cannot resolve must not render a page.
  //
  // These member routes never guarded this themselves: the shared
  // ``[slug]/layout.tsx`` called ``notFound()`` on a null Space, so by
  // the time a page ran it always had one. Giving that layout a public
  // fallback — so a discoverable-but-private Collective can show its
  // About page — removed the only guard they had, and they began
  // rendering empty-state shells to visitors: "No pathways yet" for a
  // Collective that has pathways, "No members yet" for one with
  // members. No protected data leaked (the APIs refused, which is why
  // the lists were empty) but it misrepresented the Collective and
  // handed a visitor pages they should not have.
  //
  // ``requireArea`` does not cover this: ``canReachArea`` reads a
  // missing ``area_access`` as "allow", which is deliberate for older
  // payloads but means a NULL Space passes straight through.
  //
  // Only reachable for a Collective in
  // ``PUBLICLY_DISCOVERABLE_MANAGED_SLUGS``: for every other
  // non-public Collective the layout's own fallback resolves to null
  // and 404s first, exactly as before.
  if (!space) notFound()

  // Area policy decides whether this doorway opens. The API
  // refuses independently; this stops the page shell rendering at
  // all, so nothing paints and then vanishes.
  requireArea(space, 'members')
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
        <p className="text-[14px] leading-relaxed" style={{ color: '#FFFFFF' }}>
          Meet the people who make up this collective.
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
          showMemberDirectory={space?.show_member_directory ?? true}
          learnerCount={space?.learner_count}
        />

        {/* ── Right: banner + stats + Important panel ── */}
        <div className="lg:sticky lg:top-6">
          {/* Sidebar counts come from ``space.learner_count`` /
              ``space.leader_count`` — authoritative aggregates. The
              ``learners`` / ``leaders`` lists above are privacy-
              filtered for learner-role viewers (hide learners when
              ``show_member_directory=False``), so their ``.length``
              would silently render "0 members" for ordinary members
              on this same page. */}
          <CollectiveSidebarPanel
            space={space}
            memberCount={space?.learner_count ?? 0}
            leaderCount={space?.leader_count ?? 0}
          />
        </div>

      </div>
    </div>
  )
}
