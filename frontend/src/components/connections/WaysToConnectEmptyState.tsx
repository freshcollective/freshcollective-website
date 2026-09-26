/**
 * The honest empty state.
 *
 * Most members will see this for a long time, and some will see it
 * forever, so it is written to stand on its own rather than to
 * apologise for the absence of something. Nothing here is a
 * placeholder and nothing is invented: no sample people, no sample
 * conversations, no "check back soon".
 *
 * The heading changed with the model. It used to say "Introductions
 * grow from shared experiences", from a design where Fresh Collective
 * brokered an introduction and someone accepted it. That is not what
 * this is. Nothing is offered, nothing is pending, and nobody has to
 * say yes — the platform notices what two people already share and
 * stops there. "Connection grows through shared experiences" says the
 * same warm thing about the product that actually exists.
 *
 * The doorway is the one place this component reaches for real data.
 * When a member already belongs somewhere, sending them back to
 * Explore Collectives is a shrug; a specific Gathering they could
 * actually attend is a door. When they belong nowhere, Explore
 * Collectives is exactly right.
 */

import Link from 'next/link'
import { formatGatheringFullDate } from '@/lib/dateTime'

export interface EmptyStateDoorway {
  href: string
  label: string
  /** Second line under the action — the Collective and when. */
  meta: string
}

/** Two overlapping rings: two things that share an area without
 *  becoming one thing. Decorative — the words carry the meaning. */
function OverlapMark() {
  return (
    <div className="mx-auto mb-8 flex h-14 w-14 items-center justify-center">
      <svg viewBox="0 0 40 40" width="52" height="52" aria-hidden="true">
        <circle cx="15" cy="17" r="9" stroke="#38A09E" strokeWidth="1.5" fill="none" opacity="0.7" />
        <circle cx="25" cy="23" r="9" stroke="#D4B048" strokeWidth="1.5" fill="none" opacity="0.85" />
      </svg>
    </div>
  )
}

export function buildDoorway(
  gathering: {
    id: string
    title: string
    starts_at: string
    spaceSlug: string
    spaceName: string
    timezone: string
  } | null,
): EmptyStateDoorway | null {
  if (!gathering) return null
  return {
    href: `/spaces/${gathering.spaceSlug}/events/${gathering.id}`,
    label: gathering.title,
    meta: `${gathering.spaceName} · ${formatGatheringFullDate(gathering.starts_at, gathering.timezone)}`,
  }
}

export default function WaysToConnectEmptyState({
  doorway = null,
}: {
  doorway?: EmptyStateDoorway | null
}) {
  return (
    <section className="mx-auto max-w-[720px] px-6 pb-24 pt-4 md:px-8 md:pt-6">
      <div
        className="rounded-3xl bg-white px-8 py-12 text-center md:px-12 md:py-16"
        style={{
          border: '1px solid rgba(12, 24, 38, 0.06)',
          boxShadow: '0 14px 40px rgba(12, 24, 38, 0.06), 0 2px 8px rgba(12, 24, 38, 0.03)',
        }}
      >
        <OverlapMark />

        <h2
          className="font-serif text-[22px] leading-tight md:text-[26px]"
          style={{ color: '#0C1826', letterSpacing: '-0.005em' }}
        >
          Connection grows through shared experiences.
        </h2>

        <p
          className="mx-auto mt-5 max-w-[520px] text-[15px] leading-[1.75]"
          style={{ color: 'rgba(12, 24, 38, 0.78)', fontFamily: 'Georgia, serif' }}
        >
          As you join collectives, attend gatherings and move through
          pathways, the people whose paths cross yours will appear
          here — alongside the thing you shared.
        </p>

        <p
          className="mx-auto mt-4 max-w-[520px] text-[13.5px] italic leading-[1.7]"
          style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
        >
          Nothing is shown until there is something real to show.
        </p>

        {doorway ? (
          <div className="mt-10">
            <Link
              href={doorway.href}
              className="inline-flex max-w-full flex-col items-center rounded-2xl px-7 py-4 text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              <span className="break-words text-[13.5px] font-semibold" style={{ letterSpacing: '0.02em' }}>
                {doorway.label} <span aria-hidden="true">→</span>
              </span>
              <span className="mt-0.5 text-[12px] opacity-85">{doorway.meta}</span>
            </Link>
            <p className="mt-3 text-[12.5px]" style={{ color: 'rgba(12, 24, 38, 0.5)' }}>
              One place to start.
            </p>
          </div>
        ) : (
          <div className="mt-10">
            <Link
              href="/spaces"
              className="inline-flex items-center rounded-full px-7 py-3 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                letterSpacing: '0.06em',
              }}
            >
              Explore Collectives <span aria-hidden="true">→</span>
            </Link>
          </div>
        )}
      </div>
    </section>
  )
}
