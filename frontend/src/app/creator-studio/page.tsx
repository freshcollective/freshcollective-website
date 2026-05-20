import Link from 'next/link'
import {
  getMe,
  getActiveCreatorSpace,
  getCreatorSpace,
  getCreatorPathways,
  getCreatorEvents,
  getCreatorBilling,
  getSpaceMembers,
} from '@/lib/serverApi'
import type {
  CreatorPathway,
  CreatorEvent,
  CreatorSpaceDetail,
  MemberProfile,
} from '@/types/platform'

export default async function CreatorStudioHome() {
  const [profile, activeSummary, billing] = await Promise.all([
    getMe(),
    getActiveCreatorSpace(),
    getCreatorBilling(),
  ])

  const firstName = profile?.name?.split(' ')[0] ?? 'there'

  // Full detail + content for the active collective. Members endpoint only
  // works for active (published) spaces — returns [] for draft, which is fine.
  let spaceDetail: CreatorSpaceDetail | null = null
  let pathways: CreatorPathway[] = []
  let events: CreatorEvent[] = []
  let members: MemberProfile[] = []

  if (activeSummary) {
    ;[spaceDetail, pathways, events, members] = (await Promise.all([
      getCreatorSpace(activeSummary.slug),
      getCreatorPathways(activeSummary.slug),
      getCreatorEvents(activeSummary.slug),
      getSpaceMembers(activeSummary.slug),
    ])) as [CreatorSpaceDetail | null, CreatorPathway[], CreatorEvent[], MemberProfile[]]
  }

  const now = new Date()
  const activePathways = pathways.filter((p) => p.status === 'active')
  const upcomingEvents = events.filter((e) => new Date(e.starts_at) > now)
  const memberCount = members.length
  const learnerCount = members.filter((m) => m.space_role === 'learner').length

  // ── Attention items derived from real state ────────────────────────────────
  type AttentionItem = { title: string; desc: string; href: string; action: string }
  const attention: AttentionItem[] = []

  if (spaceDetail) {
    if (spaceDetail.status !== 'active') {
      attention.push({
        title: 'Collective is still in draft',
        desc: 'Publish your collective so members can find and join it.',
        href: '/creator-studio/settings',
        action: 'Go to Settings',
      })
    }
    if (activePathways.length === 0) {
      attention.push({
        title: pathways.length > 0 ? 'No pathways published yet' : 'No pathways created yet',
        desc:
          pathways.length > 0
            ? 'You have pathways in draft — publish one when it\'s ready.'
            : 'Create your first pathway to give members a clear starting point.',
        href: '/creator-studio/pathways',
        action: 'Manage pathways',
      })
    }
    if (!spaceDetail.description) {
      attention.push({
        title: 'Description is missing',
        desc: 'Add a description so visitors understand what your collective is about.',
        href: '/creator-studio/settings',
        action: 'Add description',
      })
    }
    if (!spaceDetail.themes || spaceDetail.themes.length === 0) {
      attention.push({
        title: 'Themes are not set',
        desc: 'Add themes so your collective appears in the right category filters on Explore.',
        href: '/creator-studio/settings',
        action: 'Set themes',
      })
    }
    if (!spaceDetail.cover_image_url) {
      attention.push({
        title: 'Cover image is missing',
        desc: 'Upload a banner image to make your collective page more inviting.',
        href: '/creator-studio/settings',
        action: 'Upload image',
      })
    }
    // Only flag "no members" for published spaces — draft spaces naturally have none.
    if (spaceDetail.status === 'active' && learnerCount === 0) {
      attention.push({
        title: 'No members yet',
        desc: 'Invite people or share your collective page to welcome your first members.',
        href: '/creator-studio/people',
        action: 'Invite people',
      })
    }
    if (events.length === 0) {
      attention.push({
        title: 'No gatherings scheduled',
        desc: 'Schedule a live gathering to create momentum in your collective.',
        href: '/creator-studio/gatherings',
        action: 'Schedule gathering',
      })
    }
    if (billing && !billing.payment_setup.stripe_connect_connected) {
      attention.push({
        title: 'Payment setup is not connected yet',
        desc: 'Connect payments so members can purchase pathways or access your collective.',
        href: '/creator-studio/payments',
        action: 'Go to Payments',
      })
    }
  }

  return (
    <div className="w-full max-w-[1100px] space-y-6 px-6 py-8 md:px-10 md:py-10">

      {/* ── 1. Welcome card ── */}
      <div
        className="overflow-hidden rounded-2xl px-8 py-8"
        style={{
          background: '#071824',
          border: '1px solid rgba(56,160,158,0.18)',
          boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
        }}
      >
        <div
          className="mb-4 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
        />
        <h1 className="mb-2 font-serif text-[1.75rem] leading-tight">
          <span
            style={{
              display: 'inline-block',
              background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 40%, #FFFFFF 70%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            Welcome back, {firstName}.
          </span>
        </h1>
        <p
          className="max-w-[540px] text-[15px] leading-relaxed"
          style={{ color: 'rgba(255,255,255,0.60)' }}
        >
          Choose a collective to manage, check what needs attention, or keep building your space.
        </p>
      </div>

      {/* ── 2. Current collective snapshot ── */}
      {spaceDetail ? (
        <section>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Current collective
          </p>
          <div className="rounded-2xl border border-slate-100 bg-white p-6 shadow-sm">

            {/* Name + status badges + public link */}
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[20px] font-semibold text-navy-900">{spaceDetail.name}</h2>
                  <span
                    className="rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide"
                    style={{
                      background:
                        spaceDetail.status === 'active'
                          ? 'rgba(56,160,158,0.12)'
                          : 'rgba(0,0,0,0.06)',
                      color: spaceDetail.status === 'active' ? '#38A09E' : '#94a3b8',
                    }}
                  >
                    {spaceDetail.status === 'active' ? 'Published' : 'Draft'}
                  </span>
                  <span
                    className="rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide"
                    style={{
                      background: spaceDetail.is_public
                        ? 'rgba(56,160,158,0.08)'
                        : 'rgba(0,0,0,0.05)',
                      color: spaceDetail.is_public ? '#38A09E' : '#94a3b8',
                    }}
                  >
                    {spaceDetail.is_public ? 'Public' : 'Private'}
                  </span>
                </div>
                {spaceDetail.tagline && (
                  <p className="mt-1 text-[14px] text-slate-500">{spaceDetail.tagline}</p>
                )}
              </div>
              <Link
                href={`/spaces/${spaceDetail.slug}`}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
              >
                View public page ↗
              </Link>
            </div>

            {/* Description */}
            {spaceDetail.description && (
              <p className="mb-4 max-w-[600px] text-[14px] leading-relaxed text-slate-500">
                {spaceDetail.description}
              </p>
            )}

            {/* Themes + timezone */}
            {(spaceDetail.themes.length > 0 || spaceDetail.timezone) && (
              <div className="mb-5 flex flex-wrap items-center gap-2">
                {spaceDetail.themes.map((t) => (
                  <span
                    key={t}
                    className="rounded-lg px-2.5 py-0.5 text-[11px] font-medium"
                    style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}
                  >
                    {t}
                  </span>
                ))}
                {spaceDetail.timezone && (
                  <span className="text-[12px] text-slate-400">{spaceDetail.timezone}</span>
                )}
              </div>
            )}

            {/* Stats */}
            <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                <p className="font-serif text-2xl text-navy-900">{pathways.length}</p>
                <p className="mt-0.5 text-[13px] text-slate-500">Pathways</p>
                <p className="mt-0.5 text-[11px] text-slate-400">{activePathways.length} published</p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                <p className="font-serif text-2xl text-navy-900">{events.length}</p>
                <p className="mt-0.5 text-[13px] text-slate-500">Gatherings</p>
                <p className="mt-0.5 text-[11px] text-slate-400">{upcomingEvents.length} upcoming</p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                <p className="font-serif text-2xl text-navy-900">
                  {spaceDetail.status === 'active' ? memberCount : '—'}
                </p>
                <p className="mt-0.5 text-[13px] text-slate-500">Members</p>
                {spaceDetail.status !== 'active' && (
                  <p className="mt-0.5 text-[11px] text-slate-400">publish to see</p>
                )}
              </div>
            </div>

            {/* Quick links */}
            <div className="flex flex-wrap gap-2">
              {[
                { label: 'Edit settings', href: '/creator-studio/settings' },
                { label: 'Manage pathways', href: '/creator-studio/pathways' },
                { label: 'Schedule gathering', href: '/creator-studio/gatherings' },
                { label: 'View people', href: '/creator-studio/people' },
              ].map(({ label, href }) => (
                <Link
                  key={href}
                  href={href}
                  className="rounded-xl border border-slate-200 px-3.5 py-2 text-[13px] font-medium text-slate-600 transition-all hover:border-teal-200 hover:text-teal-700"
                >
                  {label}
                </Link>
              ))}
            </div>

          </div>
        </section>
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-medium text-navy-900">No collective selected</p>
          <p className="mb-5 text-[14px] text-slate-500">
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
      )}

      {/* ── 3. What needs attention ── */}
      {spaceDetail && (
        <section>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            What needs attention
          </p>
          {attention.length === 0 ? (
            <div
              className="rounded-2xl px-6 py-5"
              style={{
                background: 'rgba(56,160,158,0.05)',
                border: '1px solid rgba(56,160,158,0.16)',
              }}
            >
              <p className="text-[14px] font-semibold text-navy-900">Everything looks tidy.</p>
              <p className="mt-0.5 text-[13px] text-slate-500">
                Your collective has the basics in place.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {attention.map((item) => (
                <div
                  key={item.title}
                  className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-100 bg-white px-5 py-4"
                >
                  <div className="min-w-0">
                    <p className="text-[14px] font-medium text-navy-900">{item.title}</p>
                    <p className="mt-0.5 text-[13px] text-slate-500">{item.desc}</p>
                  </div>
                  <Link
                    href={item.href}
                    className="shrink-0 text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
                  >
                    {item.action} →
                  </Link>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── 4. Quick actions ── */}
      <section>
        <p
          className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Quick actions
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              label: 'Create pathway',
              desc: 'Add a new pathway to your collective',
              href: '/creator-studio/pathways',
            },
            {
              label: 'Schedule gathering',
              desc: 'Set up a live event for your members',
              href: '/creator-studio/gatherings',
            },
            {
              label: 'Invite person',
              desc: 'Add a member or moderator to your collective',
              href: '/creator-studio/people',
            },
            {
              label: 'Edit settings',
              desc: 'Update name, description, and themes',
              href: '/creator-studio/settings',
            },
            {
              label: 'Open payments',
              desc: 'Manage member payments and earnings',
              href: '/creator-studio/payments',
            },
            {
              label: 'View collective',
              desc: activeSummary
                ? `Public page for ${activeSummary.name}`
                : 'Browse all collectives',
              href: activeSummary ? `/spaces/${activeSummary.slug}` : '/spaces',
            },
          ].map(({ label, desc, href }) => (
            <Link
              key={label}
              href={href}
              className="group rounded-xl border border-slate-100 bg-white p-5 shadow-sm transition-all hover:border-teal-200 hover:shadow-md"
            >
              <p className="text-[14px] font-medium text-navy-900 transition-colors group-hover:text-teal-700">
                {label}
              </p>
              <p className="mt-1 text-[13px] text-slate-500">{desc}</p>
            </Link>
          ))}
        </div>
      </section>

      {/* ── 5. Recent activity placeholder ── */}
      <section>
        <p
          className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Recent activity
        </p>
        {/* TODO: Replace with real creator activity feed once event tracking exists. */}
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-7 py-10 text-center">
          <p className="text-[14px] leading-relaxed text-slate-500">
            Recent activity will appear here as members join, complete steps, comment,
            book gatherings, or make payments.
          </p>
        </div>
      </section>

      {/* ── 6. Payments mini-summary ── */}
      <section>
        <div
          className="flex flex-wrap items-center justify-between gap-4 rounded-2xl p-6"
          style={{
            background: 'rgba(56,160,158,0.04)',
            border: '1px solid rgba(56,160,158,0.14)',
          }}
        >
          <div>
            <p className="text-[14px] font-semibold text-navy-900">Payments</p>
            <p className="mt-0.5 text-[13px] text-slate-500">
              Payment tracking is available from your Payments page.
            </p>
          </div>
          <Link
            href="/creator-studio/payments"
            className="shrink-0 rounded-xl border border-slate-200 px-4 py-2 text-[13px] font-medium text-slate-600 transition-all hover:border-teal-200 hover:text-teal-700"
          >
            Open payments →
          </Link>
        </div>
      </section>

    </div>
  )
}
