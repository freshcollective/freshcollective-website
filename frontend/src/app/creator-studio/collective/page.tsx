import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorSpace,
  getCreatorPathways,
  getCreatorEvents,
  getCreatorPosts,
  getSpaceMembers,
} from '@/lib/serverApi'
import type { CreatorSpaceDetail, CreatorPathway, CreatorEvent, CreatorPost, MemberProfile } from '@/types/platform'

export default async function CollectiveOverviewPage() {
  const primarySpace = await getActiveCreatorSpace()

  if (!primarySpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective selected</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Create your first collective to get started.
          </p>
          <Link
            href="/creator-studio/create"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create collective
          </Link>
        </div>
      </div>
    )
  }

  const [detail, pathways, events, posts, members]: [
    CreatorSpaceDetail | null,
    CreatorPathway[],
    CreatorEvent[],
    CreatorPost[],
    MemberProfile[],
  ] = await Promise.all([
    getCreatorSpace(primarySpace.slug),
    getCreatorPathways(primarySpace.slug),
    getCreatorEvents(primarySpace.slug),
    getCreatorPosts(primarySpace.slug),
    getSpaceMembers(primarySpace.slug),
  ])

  const space = detail ?? { ...primarySpace, description: null, is_public: false, cover_image_url: null }

  const now = new Date()
  const upcoming = events.filter((e) => new Date(e.starts_at) >= now)
  const activePathways = pathways.filter((p) => p.status === 'active')
  const isPublished = primarySpace.status === 'active'

  // Decide the most useful next action
  let nextAction: { label: string; href: string; desc: string } | null = null
  if (pathways.length === 0) {
    nextAction = {
      label: 'Add your first pathway',
      href: `/creator/spaces/${primarySpace.slug}/pathways`,
      desc: 'A pathway is a structured sequence of steps that guides members through your work.',
    }
  } else if (!isPublished) {
    nextAction = {
      label: 'Publish your collective',
      href: '/creator-studio/settings',
      desc: 'Set your collective status to Active so members can find and join it.',
    }
  } else if (upcoming.length === 0) {
    nextAction = {
      label: 'Schedule a gathering',
      href: `/creator/spaces/${primarySpace.slug}/events/new`,
      desc: 'Live sessions, workshops, or circles keep your community connected.',
    }
  }

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {/* Page header */}
      <div className="mb-8">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span
            className="rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide"
            style={{
              background: isPublished ? 'rgba(56,160,158,0.12)' : 'rgba(0,0,0,0.06)',
              color: isPublished ? '#38A09E' : '#94a3b8',
            }}
          >
            {isPublished ? 'Active' : 'Draft'}
          </span>
        </div>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">
          {space.name}
        </h1>
        {space.tagline && (
          <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
            {space.tagline}
          </p>
        )}
      </div>

      {/* Banner image */}
      {space.cover_image_url && (
        <div className="mb-6 overflow-hidden rounded-2xl border border-slate-200">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={space.cover_image_url}
            alt={`${space.name} banner`}
            className="h-44 w-full object-cover"
          />
        </div>
      )}

      {/* Stats */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          { label: 'Pathways',   value: pathways.length },
          { label: 'Published',  value: activePathways.length },
          { label: 'Gatherings', value: events.length },
          { label: 'Posts',      value: posts.length },
          { label: 'People',     value: members.length },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-white p-4">
            <p className="font-serif text-2xl text-navy-900">{value}</p>
            <p className="mt-0.5 text-[13px] text-slate-500">{label}</p>
          </div>
        ))}
      </div>

      {/* Next action card */}
      {nextAction && (
        <div
          className="mb-6 rounded-xl border px-7 py-6"
          style={{
            borderColor: 'rgba(56,160,158,0.18)',
            background: 'linear-gradient(135deg, #071824 0%, #073B3A 100%)',
          }}
        >
          <p
            className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#8DE8E6' }}
          >
            Next step
          </p>
          <p className="mb-1.5 font-serif text-xl text-white">{nextAction.label}</p>
          <p
            className="mb-5 max-w-md text-[14px] leading-relaxed"
            style={{ color: 'rgba(255,255,255,0.75)' }}
          >
            {nextAction.desc}
          </p>
          <Link
            href={nextAction.href}
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {nextAction.label}
          </Link>
        </div>
      )}

      {/* Quick actions */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[
          {
            label: 'Build pathways',
            desc: pathways.length > 0 ? `${pathways.length} pathway${pathways.length !== 1 ? 's' : ''}` : 'None yet',
            href: `/creator/spaces/${primarySpace.slug}/pathways`,
          },
          {
            label: 'Schedule gathering',
            desc: upcoming.length > 0 ? `${upcoming.length} upcoming` : 'None scheduled',
            href: `/creator/spaces/${primarySpace.slug}/events/new`,
          },
          {
            label: 'Community',
            desc: posts.length > 0 ? `${posts.length} post${posts.length !== 1 ? 's' : ''}` : 'No posts yet',
            href: '/creator-studio/community',
          },
          {
            label: 'Manage people',
            desc: members.length > 0 ? `${members.length} member${members.length !== 1 ? 's' : ''}` : 'No members yet',
            href: '/creator-studio/people',
          },
          {
            label: 'Edit settings',
            desc: 'Name, banner, visibility',
            href: '/creator-studio/settings',
          },
          {
            label: 'Edit About page',
            desc: 'Description shown on the About tab',
            href: '/creator-studio/settings',
          },
        ].map(({ label, desc, href }) => (
          <Link
            key={href}
            href={href}
            className="group rounded-xl border border-border bg-white p-5 transition-all hover:border-teal-200 hover:shadow-sm"
          >
            <p className="text-[14px] font-medium text-navy-900 transition-colors group-hover:text-teal-700">
              {label}
            </p>
            <p className="mt-1 text-[13px] text-slate-500">{desc}</p>
          </Link>
        ))}
      </div>

    </div>
  )
}
