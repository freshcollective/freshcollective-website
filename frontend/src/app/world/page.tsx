import Link from 'next/link'
import { getMyMemberships } from '@/lib/serverApi'
import {
  COLLECTIVES,
  collectWorldElementsFor,
  isMemberOf,
} from '@/lib/world/collectives'
import type { SpaceMembership } from '@/types/platform'
import WorldSky from '@/components/world/WorldSky'
import MyWorldPreview from '@/components/world/MyWorldPreview'

/**
 * `/world` — the emotional centre of Fresh Collective.
 *
 * The page reads top to bottom as a single continuous night: shared sky,
 * warm greeting, personal world, and a quiet row of doors into the rest
 * of the platform. No cards, no dashboard chrome — the atmosphere carries
 * the layout.
 *
 * Data comes from the real memberships API. Slugs are resolved through
 * the `memberSlugs` field on each collective so renames don't drop
 * anyone's world elements. When a collective has no seeded home yet, its
 * sky constellation renders as "Forming" and its wander-card is muted.
 */
export default async function WorldPage() {
  const memberships: SpaceMembership[] = await getMyMemberships()
  const memberSlugs = memberships
    .filter((m) => m.status === 'active' || m.status === 'trialing')
    .map((m) => m.space_slug)

  const worldElements = collectWorldElementsFor(memberSlugs)
  const firstMembershipSlug = memberships[0]?.space_slug ?? null

  // Resolve activity links: prefer the member's own collectives, then any
  // available collective home, then null (card renders muted).
  const eventsHref = firstMembershipSlug
    ? `/spaces/${firstMembershipSlug}/events`
    : COLLECTIVES.find((c) => c.href)?.href
      ? `${COLLECTIVES.find((c) => c.href)!.href}/events`
      : null
  const communityHref = firstMembershipSlug
    ? `/spaces/${firstMembershipSlug}/community`
    : COLLECTIVES.find((c) => c.href)?.href
      ? `${COLLECTIVES.find((c) => c.href)!.href}/community`
      : null

  return (
    <main
      className="min-h-screen w-full"
      style={{ background: '#030814' }}
    >
      {/* The sky */}
      <WorldSky memberSlugs={memberSlugs} />

      {/* Warm heading + gentle prompt */}
      <section className="mx-auto max-w-[820px] px-6 pb-6 pt-16 text-center md:pt-20">
        <h1
          className="font-serif text-3xl leading-tight md:text-[42px] md:leading-[1.15]"
          style={{ color: '#F7EFC7' }}
        >
          Welcome back. Your world is here.
        </h1>
        <p
          className="mx-auto mt-5 max-w-[560px] text-[15px] italic leading-relaxed"
          style={{ color: 'rgba(247, 239, 199, 0.72)', fontFamily: 'Georgia, serif' }}
        >
          What part of your world is asking for your attention today?
        </p>
      </section>

      {/* My World — full-bleed, no card */}
      <section className="relative w-full pb-4">
        <MyWorldPreview elements={worldElements} />
        {worldElements.length > 0 && (
          <p
            className="mx-auto mt-2 max-w-[560px] px-6 text-center text-[11px] uppercase tracking-[0.28em]"
            style={{ color: 'rgba(247, 239, 199, 0.42)' }}
          >
            {worldElements.join(' · ')}
          </p>
        )}
      </section>

      {/* Where you might wander */}
      <section className="mx-auto max-w-[1080px] px-6 pb-24 pt-10">
        <p
          className="mb-6 text-center text-[11px] font-semibold uppercase tracking-[0.28em]"
          style={{ color: 'rgba(247, 239, 199, 0.55)' }}
        >
          Where you might wander
        </p>
        <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-5">
          {COLLECTIVES.map((c) => (
            <WanderLink
              key={c.id}
              href={c.href}
              accent={c.accent}
              title={c.name}
              subtitle={c.tagline}
              highlight={isMemberOf(c, memberSlugs)}
            />
          ))}
          <WanderLink
            href={eventsHref}
            accent="#F7EFC7"
            title="Upcoming gatherings"
            subtitle="Live moments unfolding in the collectives."
          />
          <WanderLink
            href={communityHref}
            accent="#8DE8E6"
            title="Recent conversations"
            subtitle="What people are noticing and asking, together."
          />
        </div>
      </section>
    </main>
  )
}

// ---------------------------------------------------------------------------
// WanderLink — a subtle door, not a card. Renders as a muted whisper when
// there is no href yet.
// ---------------------------------------------------------------------------

function WanderLink({
  href, accent, title, subtitle, highlight = false,
}: {
  href: string | null
  accent: string
  title: string
  subtitle: string
  highlight?: boolean
}) {
  const inner = (
    <>
      <div
        className="mb-3 h-[2px] w-6 rounded-full transition-all duration-500 group-hover:w-10"
        style={{
          background: `linear-gradient(90deg, ${accent} 0%, transparent 100%)`,
          opacity: href ? (highlight ? 0.95 : 0.75) : 0.35,
        }}
      />
      <p
        className="text-[13.5px] font-semibold leading-snug"
        style={{ color: href ? '#F7EFC7' : 'rgba(247,239,199,0.55)' }}
      >
        {title}
      </p>
      <p
        className="mt-1 text-[12px] leading-relaxed"
        style={{ color: href ? 'rgba(247,239,199,0.62)' : 'rgba(247,239,199,0.42)' }}
      >
        {subtitle}
      </p>
      {!href && (
        <p
          className="mt-2 text-[10px] uppercase tracking-[0.24em]"
          style={{ color: 'rgba(247,239,199,0.45)' }}
        >
          Forming
        </p>
      )}
    </>
  )

  const shared = 'group relative block overflow-hidden rounded-2xl px-4 py-4 transition-colors'
  const bg = highlight
    ? 'rgba(141, 232, 230, 0.04)'
    : 'rgba(247, 239, 199, 0.025)'
  const border = highlight
    ? '1px solid rgba(141, 232, 230, 0.20)'
    : '1px solid rgba(247, 239, 199, 0.08)'

  if (href) {
    return (
      <Link href={href} className={shared} style={{ background: bg, border }}>
        {inner}
      </Link>
    )
  }
  return (
    <div className={shared} style={{ background: bg, border }} aria-label={`${title} — forming`}>
      {inner}
    </div>
  )
}
