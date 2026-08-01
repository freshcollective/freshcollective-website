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
 * Collective Overview — the default landing after entering or switching
 * to a collective. Formerly "Home"; route path unchanged.
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

// Palette tokens used across the page. Kept local (rather than reaching
// for a shared design-token file) so the polish stays scoped to this
// route without cross-file churn.
const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const NAVY = '#0C1826'
const INK_CHARCOAL = 'rgba(12, 24, 38, 0.78)'  // primary secondary text
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'      // slightly quieter body copy
const INK_TERTIARY = 'rgba(12, 24, 38, 0.48)'  // timestamps, helper hints
const HAIRLINE = '1px solid rgba(12, 24, 38, 0.06)'
const TEAL_TINT_BG = 'rgba(56, 160, 158, 0.10)'
const GOLD_TINT_BG = 'rgba(212, 176, 72, 0.14)'

type Tint = 'teal' | 'gold'

export default async function CreatorStudioCollectiveHome() {
  const activeSummary = await getActiveCreatorSpace()

  if (!activeSummary) {
    return (
      <div className="mx-auto max-w-[1180px] px-8 py-10 md:px-10 md:py-14">
        <SectionEyebrow label="Collective Overview" />
        <h1 className="mt-3 font-serif text-[28px] leading-tight text-navy-900 md:text-[36px]">
          You don&apos;t have a collective yet.
        </h1>
        <p
          className="mt-3 max-w-md text-[15px] leading-relaxed italic"
          style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
        >
          Head back to Your World to build your first collective.
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
        href: '/creator-studio/settings?tab=place',
        action: 'Set Place & Feel',
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
  type Moment = { icon: string; tint: Tint; text: string; when: string; href?: string }
  const moments: Moment[] = []

  // Recent pathway updates (top 3 by updated_at)
  const recentPathways = [...pathways]
    .sort((a, b) => +new Date(b.updated_at || b.created_at) - +new Date(a.updated_at || a.created_at))
    .slice(0, 3)
  recentPathways.forEach((p) => {
    const stamp = p.updated_at || p.created_at
    moments.push({
      icon: '📖',
      tint: 'teal',
      text: `Pathway "${p.title}" was updated`,
      when: stamp,
      href: `/creator-studio/pathways/${p.slug}`,
    })
  })

  // Nearest upcoming gathering — gold tint marks the celebratory nature
  if (upcomingEvents.length > 0) {
    const next = upcomingEvents[0]
    moments.push({
      icon: '📅',
      tint: 'gold',
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
      tint: 'teal',
      text: `${m.display_name ?? 'A member'} joined`,
      when: m.joined_at ?? '',
      href: '/creator-studio/people',
    })
  })

  moments.sort((a, b) => +new Date(b.when || 0) - +new Date(a.when || 0))
  const recentMoments = moments.slice(0, 6)

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <CollectiveArtworkHeader
        collectiveName={activeSummary.name}
        sectionTitle="Collective Overview"
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
            <div className="mb-4 flex items-baseline justify-between gap-4">
              <h2 className="font-serif text-[22px] leading-tight text-navy-900">
                Today&apos;s focus
              </h2>
              {focus.length > 0 && (
                <span
                  className="shrink-0 rounded-full px-3 py-1 text-[11px] font-semibold"
                  style={{ background: TEAL_TINT_BG, color: TEAL_DEEP }}
                >
                  {focus.length} {focus.length === 1 ? 'thing' : 'things'} waiting
                </span>
              )}
            </div>
            {focus.length === 0 ? (
              <div
                className="overflow-hidden rounded-2xl px-6 py-9 text-center"
                style={{
                  background:
                    'linear-gradient(135deg, rgba(56, 160, 158, 0.08) 0%, rgba(212, 176, 72, 0.06) 100%)',
                  border: '1px solid rgba(56, 160, 158, 0.14)',
                }}
              >
                <div
                  className="mx-auto mb-4 flex h-9 w-9 items-center justify-center rounded-full"
                  style={{ background: '#FFFFFF', border: `1px solid ${TEAL_TINT_BG}` }}
                  aria-hidden="true"
                >
                  <span style={{ color: TEAL_DEEP, fontSize: 16 }}>✓</span>
                </div>
                <p className="font-serif text-[17px] leading-snug text-navy-900">
                  Everything looks good today.
                </p>
                <p
                  className="mx-auto mt-2 max-w-sm text-[13.5px] italic leading-relaxed"
                  style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
                >
                  No draft content waiting, no gatherings needing attention.
                </p>
              </div>
            ) : (
              <ul className="space-y-2.5">
                {focus.map((item, i) => (
                  <li key={i}>
                    <FocusCard item={item} />
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
                  color: INK_SOFT,
                  fontFamily: 'Georgia, serif',
                  border: HAIRLINE,
                }}
              >
                Nothing yet — as members arrive and pathways move, they&apos;ll appear here.
              </p>
            ) : (
              <ul className="space-y-2">
                {recentMoments.map((m, i) => (
                  <li key={i}>
                    <MomentRow moment={m} />
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
            <SectionEyebrow label="Snapshot" />
            <dl className="mt-3 grid grid-cols-2 gap-3">
              <SnapCell
                label="Members"
                value={memberCount}
                href="/creator-studio/people"
                icon="👥"
                tint="teal"
              />
              <SnapCell
                label="Pathways"
                value={pathways.length}
                href="/creator-studio/pathways"
                icon="🧭"
                tint="teal"
              />
              <SnapCell
                label="Upcoming gatherings"
                value={upcomingEvents.length}
                href="/creator-studio/gatherings"
                icon="📅"
                tint="gold"
              />
              <SnapCell
                label="Conversations"
                value={null}
                href="/creator-studio/community"
                icon="💬"
                tint="teal"
              />
            </dl>
          </section>

          {/* Quick actions */}
          <section>
            <SectionEyebrow label="What to do next" />
            <div className="mt-3 space-y-2">
              <QuickAction
                href="/creator-studio/pathways/new"
                label="Create pathway"
                icon="🧭"
                tint="teal"
              />
              <QuickAction
                href="/creator-studio/gatherings"
                label="Create gathering"
                icon="📅"
                tint="gold"
              />
              <QuickAction
                href="/creator-studio/community"
                label="Start a conversation"
                icon="💬"
                tint="teal"
              />
              <QuickAction
                href="/creator-studio/resources"
                label="Add a resource"
                icon="📎"
                tint="gold"
              />
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared bits — kept inline so the polish stays contained to this route
// ---------------------------------------------------------------------------

function SectionEyebrow({ label }: { label: string }) {
  return (
    <p
      className="text-[10.5px] font-semibold uppercase tracking-[0.24em]"
      style={{ color: TEAL }}
    >
      {label}
    </p>
  )
}

function TintedIcon({
  icon, tint, size = 34,
}: {
  icon: string
  tint: Tint
  size?: number
}) {
  const bg = tint === 'gold' ? GOLD_TINT_BG : TEAL_TINT_BG
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full"
      style={{
        background: bg,
        width: size,
        height: size,
        fontSize: Math.round(size * 0.48),
        lineHeight: 1,
      }}
      aria-hidden="true"
    >
      {icon}
    </span>
  )
}

function FocusCard({
  item,
}: {
  item: { title: string; desc: string; href: string; action: string }
}) {
  return (
    <Link
      href={item.href}
      className="group relative flex items-start justify-between gap-4 overflow-hidden rounded-xl bg-white px-5 py-4 pl-6 transition-colors"
      style={{ border: HAIRLINE }}
    >
      {/* Teal accent stripe on the left — gives the section its warmer presence */}
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-0 w-[3px]"
        style={{
          background: `linear-gradient(180deg, ${TEAL} 0%, rgba(56, 160, 158, 0.55) 100%)`,
        }}
      />
      <div className="min-w-0">
        <p className="text-[14.5px] font-semibold text-navy-900">{item.title}</p>
        <p className="mt-1 text-[13px] leading-relaxed" style={{ color: INK_CHARCOAL }}>
          {item.desc}
        </p>
      </div>
      <span
        className="mt-1 shrink-0 text-[12.5px] font-semibold transition-transform group-hover:translate-x-0.5"
        style={{ color: TEAL_DEEP }}
      >
        {item.action} →
      </span>
      {/* Soft teal hover wash */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100"
        style={{ background: 'rgba(56, 160, 158, 0.04)' }}
      />
    </Link>
  )
}

function MomentRow({
  moment,
}: {
  moment: { icon: string; tint: Tint; text: string; when: string; href?: string }
}) {
  const interior = (
    <>
      <TintedIcon icon={moment.icon} tint={moment.tint} size={32} />
      <span
        className="min-w-0 flex-1 text-[14px] leading-relaxed"
        style={{ color: NAVY }}
      >
        {moment.text}
      </span>
      <span
        className="shrink-0 text-[11.5px] font-medium"
        style={{ color: INK_TERTIARY }}
      >
        {formatRelative(moment.when)}
      </span>
    </>
  )
  const baseClass = 'group relative flex items-center gap-3 overflow-hidden rounded-xl bg-white px-4 py-3 transition-colors'
  const baseStyle = { border: HAIRLINE }
  const hoverWash = (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100"
      style={{ background: 'rgba(56, 160, 158, 0.05)' }}
    />
  )
  if (moment.href) {
    return (
      <Link href={moment.href} className={baseClass} style={baseStyle}>
        {interior}
        {hoverWash}
      </Link>
    )
  }
  return (
    <div className={baseClass.replace(' group', '')} style={baseStyle}>
      {interior}
    </div>
  )
}

function SnapCell({
  label, value, href, icon, tint,
}: {
  label: string
  value: number | null
  href: string
  icon: string
  tint: Tint
}) {
  return (
    <Link
      href={href}
      className="group relative overflow-hidden rounded-xl bg-white px-4 py-3.5 transition-colors"
      style={{ border: HAIRLINE }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p
            className="text-[11px] font-medium uppercase tracking-[0.10em]"
            style={{ color: INK_SOFT }}
          >
            {label}
          </p>
          <p
            className="mt-1.5 font-serif text-[24px] leading-none"
            style={{ color: NAVY }}
          >
            {value ?? <span className="text-[15px] italic" style={{ color: INK_TERTIARY }}>—</span>}
          </p>
        </div>
        <TintedIcon icon={icon} tint={tint} size={30} />
      </div>
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100"
        style={{ background: 'rgba(56, 160, 158, 0.05)' }}
      />
    </Link>
  )
}

function QuickAction({
  href, label, icon, tint,
}: {
  href: string
  label: string
  icon: string
  tint: Tint
}) {
  return (
    <Link
      href={href}
      className="group relative flex items-center gap-3 overflow-hidden rounded-xl bg-white px-4 py-3 transition-colors"
      style={{ border: HAIRLINE }}
    >
      <TintedIcon icon={icon} tint={tint} size={30} />
      <span
        className="flex-1 text-[13.5px] font-semibold"
        style={{ color: NAVY }}
      >
        {label}
      </span>
      <span
        aria-hidden="true"
        className="shrink-0 text-[13px] font-semibold transition-transform group-hover:translate-x-0.5"
        style={{ color: TEAL_DEEP }}
      >
        →
      </span>
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100"
        style={{ background: 'rgba(56, 160, 158, 0.05)' }}
      />
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

