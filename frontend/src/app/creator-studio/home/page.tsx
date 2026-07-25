import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorSpace,
  getCreatorPathways,
  getCreatorEvents,
  getSpaceMembers,
} from '@/lib/serverApi'
import type {
  CreatorEvent,
  CreatorPathway,
  CreatorSpaceDetail,
  MemberProfile,
} from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'

/**
 * Collective Home — the default landing after entering or switching
 * to a collective.
 *
 * Answers, in order:
 *   1. Which collective am I in?   → the artwork hero at the top
 *   2. What needs my attention?    → Today's focus
 *   3. What is happening here?     → Collective snapshot
 *   4. What has happened recently? → Recent moments
 *   5. What could I do next?       → Quiet quick actions
 *
 * All data derives from existing endpoints. No new backend surface.
 */

export default async function CreatorStudioCollectiveHome() {
  const activeSummary = await getActiveCreatorSpace()

  if (!activeSummary) {
    return (
      <div className="mx-auto max-w-[1180px] px-8 py-10 md:px-10 md:py-14">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">
          Home
        </p>
        <h1 className="font-serif text-[28px] leading-tight text-navy-900 md:text-[36px]">
          You don&apos;t have a collective yet.
        </h1>
        <p
          className="mt-3 max-w-md text-[15px] leading-relaxed italic"
          style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
        >
          Head back to Your World to build your first collective, or pick one from the switcher.
        </p>
        <div className="mt-6 flex gap-3">
          <Link
            href="/creator-studio"
            className="inline-flex items-center rounded-full px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Your World →
          </Link>
        </div>
      </div>
    )
  }

  const [spaceDetail, pathways, events, members] = await Promise.all([
    getCreatorSpace(activeSummary.slug) as Promise<CreatorSpaceDetail | null>,
    getCreatorPathways(activeSummary.slug) as Promise<CreatorPathway[]>,
    getCreatorEvents(activeSummary.slug) as Promise<CreatorEvent[]>,
    getSpaceMembers(activeSummary.slug) as Promise<MemberProfile[]>,
  ])

  const now = new Date()
  const activePathways = pathways.filter((p) => p.status === 'active')
  const draftPathways = pathways.filter((p) => p.status === 'draft')
  const upcomingEvents = events
    .filter((e) => new Date(e.starts_at) > now)
    .sort((a, b) => +new Date(a.starts_at) - +new Date(b.starts_at))
  const memberCount = members.length
  const learnerCount = members.filter((m) => m.space_role === 'learner').length
  const isDraft = spaceDetail?.status !== 'active'

  // ── Today's focus ────────────────────────────────────────────────────
  type FocusItem = { title: string; desc: string; href: string; action: string }
  const focus: FocusItem[] = []

  if (spaceDetail) {
    if (isDraft) {
      focus.push({
        title: 'Collective is still in draft',
        desc: 'Publish this collective so people can find and join it.',
        href: '/creator-studio/settings?tab=visibility',
        action: 'Open Visibility',
      })
    }
    if (draftPathways.length > 0) {
      focus.push({
        title: `${draftPathways.length} ${draftPathways.length === 1 ? 'pathway' : 'pathways'} in draft`,
        desc: 'Publish or continue building.',
        href: '/creator-studio/pathways',
        action: 'Open Pathways',
      })
    }
    if (activePathways.length === 0 && draftPathways.length === 0) {
      focus.push({
        title: 'No pathways yet',
        desc: 'Guided journeys give members somewhere to begin.',
        href: '/creator-studio/pathways/new',
        action: 'Create pathway',
      })
    }
    if (!spaceDetail.description) {
      focus.push({
        title: 'Short description is missing',
        desc: 'A one-line summary helps people understand what this collective is.',
        href: '/creator-studio/settings?tab=details',
        action: 'Add description',
      })
    }
    if ((spaceDetail.themes ?? []).length === 0) {
      focus.push({
        title: 'Themes are not set',
        desc: 'Themes help this collective appear in the right places on Explore.',
        href: '/creator-studio/settings?tab=details',
        action: 'Set themes',
      })
    }
    if (!spaceDetail.cover_image_url && !spaceDetail.location?.hero_artwork_url) {
      focus.push({
        title: 'No banner or Location artwork',
        desc: 'A banner or Location gives this collective a stronger visual identity.',
        href: '/creator-studio/settings?tab=artwork',
        action: 'Set artwork',
      })
    }
    if (!isDraft && learnerCount === 0) {
      focus.push({
        title: 'No members yet',
        desc: 'Share the About page with the people you\'d love to gather.',
        href: `/spaces/${spaceDetail.slug}/about`,
        action: 'Open public page',
      })
    }
  }

  // ── Recent moments ───────────────────────────────────────────────────
  type Moment = { icon: string; text: string; when: string; href?: string }
  const moments: Moment[] = []

  // Recent pathway updates (top 3 by updated_at)
  const recentPathways = [...pathways]
    .sort((a, b) => +new Date(b.updated_at || b.created_at) - +new Date(a.updated_at || a.created_at))
    .slice(0, 3)
  recentPathways.forEach((p) => {
    const stamp = p.updated_at || p.created_at
    moments.push({
      icon: '📖',
      text: `Pathway "${p.title}" was updated`,
      when: stamp,
      href: `/creator-studio/pathways/${p.slug}`,
    })
  })

  // Nearest upcoming gathering
  if (upcomingEvents.length > 0) {
    const next = upcomingEvents[0]
    moments.push({
      icon: '📅',
      text: `Next gathering: "${next.title}"`,
      when: next.starts_at,
      href: '/creator-studio/gatherings',
    })
  }

  // Recent member joins (top 3 by joined_at if present)
  const recentJoins = [...members]
    .filter((m) => m.joined_at)
    .sort((a, b) => +new Date(b.joined_at ?? 0) - +new Date(a.joined_at ?? 0))
    .slice(0, 3)
  recentJoins.forEach((m) => {
    moments.push({
      icon: '🤝',
      text: `${m.display_name ?? 'A member'} joined`,
      when: m.joined_at ?? '',
      href: '/creator-studio/people',
    })
  })

  moments.sort((a, b) => +new Date(b.when || 0) - +new Date(a.when || 0))
  const recentMoments = moments.slice(0, 6)

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {/* Hero — the collective's own artwork sets the atmosphere */}
      <CollectiveArtworkHeader
        collectiveName={activeSummary.name}
        sectionTitle={activeSummary.name}
        meta={
          <>
            {spaceDetail?.tagline
              ? <span>{spaceDetail.tagline}</span>
              : <span>{isDraft ? 'A quiet draft, ready for what comes next.' : 'Alive and open.'}</span>}
            {spaceDetail?.location?.name && (
              <>
                <span className="mx-2 text-white/50" aria-hidden="true">·</span>
                <span>{spaceDetail.location.name}</span>
              </>
            )}
            <span className="mx-2 text-white/50" aria-hidden="true">·</span>
            <span>{isDraft ? 'Draft' : 'Live'}</span>
          </>
        }
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
      />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">

        {/* ── LEFT column ─── */}
        <div className="min-w-0 space-y-10">

          {/* Today's focus */}
          <section>
            <div className="mb-4 flex items-baseline justify-between">
              <h2 className="font-serif text-[22px] leading-tight text-navy-900">
                Today&apos;s focus
              </h2>
              {focus.length > 0 && (
                <p className="text-[12.5px] text-slate-500">
                  {focus.length} {focus.length === 1 ? 'thing' : 'things'} waiting
                </p>
              )}
            </div>
            {focus.length === 0 ? (
              <div
                className="rounded-2xl px-6 py-8 text-center"
                style={{ background: '#FBFAF6' }}
              >
                <p
                  className="font-serif text-[17px] leading-snug text-navy-900"
                >
                  Everything looks good today.
                </p>
                <p
                  className="mx-auto mt-2 max-w-sm text-[13.5px] italic leading-relaxed"
                  style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
                >
                  No draft content waiting, no gatherings needing attention.
                </p>
              </div>
            ) : (
              <ul className="space-y-2">
                {focus.map((item, i) => (
                  <li key={i}>
                    <Link
                      href={item.href}
                      className="group flex items-start justify-between gap-4 rounded-xl bg-white px-5 py-4 transition-colors hover:bg-slate-50"
                      style={{ border: '1px solid rgba(12, 24, 38, 0.06)' }}
                    >
                      <div className="min-w-0">
                        <p className="text-[14px] font-medium text-navy-900">{item.title}</p>
                        <p className="mt-1 text-[13px] leading-relaxed text-slate-600">{item.desc}</p>
                      </div>
                      <span
                        className="mt-1 shrink-0 text-[12.5px] font-medium text-teal-700 transition-transform group-hover:translate-x-0.5"
                      >
                        {item.action} →
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Recent moments */}
          <section>
            <h2 className="mb-4 font-serif text-[22px] leading-tight text-navy-900">
              Recent moments
            </h2>
            {recentMoments.length === 0 ? (
              <p
                className="rounded-2xl bg-white px-5 py-6 text-[13.5px] italic"
                style={{
                  color: 'rgba(12, 24, 38, 0.60)',
                  fontFamily: 'Georgia, serif',
                  border: '1px solid rgba(12, 24, 38, 0.06)',
                }}
              >
                Nothing yet — as members arrive and pathways move, they&apos;ll appear here.
              </p>
            ) : (
              <ul className="space-y-2">
                {recentMoments.map((m, i) => (
                  <li key={i}>
                    {m.href ? (
                      <Link
                        href={m.href}
                        className="flex items-center gap-3 rounded-xl bg-white px-5 py-3 transition-colors hover:bg-slate-50"
                        style={{ border: '1px solid rgba(12, 24, 38, 0.06)' }}
                      >
                        <span aria-hidden="true" className="text-[15px]">{m.icon}</span>
                        <span className="min-w-0 flex-1 text-[13.5px] leading-relaxed text-navy-900">
                          {m.text}
                        </span>
                        <span className="shrink-0 text-[11.5px] text-slate-500">
                          {formatRelative(m.when)}
                        </span>
                      </Link>
                    ) : (
                      <div
                        className="flex items-center gap-3 rounded-xl bg-white px-5 py-3"
                        style={{ border: '1px solid rgba(12, 24, 38, 0.06)' }}
                      >
                        <span aria-hidden="true" className="text-[15px]">{m.icon}</span>
                        <span className="min-w-0 flex-1 text-[13.5px] leading-relaxed text-navy-900">
                          {m.text}
                        </span>
                        <span className="shrink-0 text-[11.5px] text-slate-500">
                          {formatRelative(m.when)}
                        </span>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* ── RIGHT column ─── */}
        <div className="space-y-8 lg:pt-2">

          {/* Snapshot */}
          <section>
            <p className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              Snapshot
            </p>
            <dl className="grid grid-cols-2 gap-3">
              <SnapCell label="Members" value={memberCount} href="/creator-studio/people" />
              <SnapCell label="Pathways" value={pathways.length} href="/creator-studio/pathways" />
              <SnapCell label="Upcoming gatherings" value={upcomingEvents.length} href="/creator-studio/gatherings" />
              <SnapCell label="Conversations" value={null} href="/creator-studio/community" />
            </dl>
          </section>

          {/* Quick actions */}
          <section>
            <p className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              What to do next
            </p>
            <div className="space-y-2">
              <QuickAction href="/creator-studio/pathways/new" label="Create pathway" />
              <QuickAction href="/creator-studio/gatherings" label="Create gathering" />
              <QuickAction href="/creator-studio/community" label="Start a conversation" />
              <QuickAction href="/creator-studio/resources" label="Add a resource" />
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function SnapCell({
  label, value, href,
}: {
  label: string
  value: number | null
  href: string
}) {
  return (
    <Link
      href={href}
      className="rounded-xl bg-white px-4 py-3 transition-colors hover:bg-slate-50"
      style={{ border: '1px solid rgba(12, 24, 38, 0.06)' }}
    >
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="mt-1 font-serif text-[20px] leading-none text-navy-900">
        {value ?? <span className="text-[14px] italic text-slate-400">—</span>}
      </p>
    </Link>
  )
}

function QuickAction({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="flex items-center justify-between rounded-xl bg-white px-4 py-3 text-[13px] font-medium text-slate-700 transition-colors hover:bg-slate-50 hover:text-navy-900"
      style={{ border: '1px solid rgba(12, 24, 38, 0.06)' }}
    >
      <span>{label}</span>
      <span aria-hidden="true" className="text-teal-700">→</span>
    </Link>
  )
}

function formatRelative(iso: string): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (isNaN(then)) return ''
  const now = Date.now()
  const diff = Math.abs(now - then)
  const past = now > then
  const min = 60_000
  const hour = 60 * min
  const day = 24 * hour
  if (diff < min) return past ? 'just now' : 'soon'
  if (diff < hour) return past ? `${Math.floor(diff / min)}m ago` : `in ${Math.floor(diff / min)}m`
  if (diff < day) return past ? `${Math.floor(diff / hour)}h ago` : `in ${Math.floor(diff / hour)}h`
  if (diff < 7 * day) return past ? `${Math.floor(diff / day)}d ago` : `in ${Math.floor(diff / day)}d`
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}
