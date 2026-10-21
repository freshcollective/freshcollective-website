import { getSpace, getMemberOfferings } from '@/lib/serverApi'
import { requireArea } from '@/lib/areaAccess'
import OfferingCard from '@/components/spaces/OfferingCard'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type { OfferingCard as OfferingCardData, SpaceResponse } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

/**
 * A Collective's Offerings catalogue.
 *
 * Open to anonymous visitors, which is the premise of this phase:
 * people find a creator through a resource, and that cannot happen if
 * finding one requires already belonging. ``requireArea`` still guards
 * the page, and while the Offerings feature is off the backend omits
 * ``offerings`` from ``area_access`` — so this route, the nav tab and
 * the Collective Home all close from one switch.
 *
 * Laid out to match the Pathways doorway exactly: the same dark intro
 * card, the same two-column card grid, the same right sidebar. An
 * Offering is another thing this Collective holds, not an arrival
 * somewhere else.
 */
export default async function SpaceOfferingsPage({ params }: Props) {
  const { slug } = await params

  const [offerings, space]: [OfferingCardData[] | null, SpaceResponse | null] =
    await Promise.all([
      getMemberOfferings(slug),
      getSpace(slug),
    ])

  // Area policy decides whether this doorway opens. The API refuses
  // independently; this stops the page shell rendering at all, so
  // nothing paints and then vanishes.
  requireArea(space, 'offerings')

  const cards = offerings ?? []
  const memberCount = space?.learner_count ?? 0
  const leaderCount = space?.leader_count ?? 0

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">

      {/* ── Main column ── */}
      <div className="min-w-0">

        {/* Intro card — the Pathways pattern, same tokens. */}
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
              Offerings
            </span>
          </h2>
          <p className="text-[14px] leading-relaxed" style={{ color: '#FFFFFF' }}>
            Resources from this Collective to download and keep.
          </p>
        </div>

        {cards.length === 0 ? (
          <div
            className="rounded-2xl border bg-white px-7 py-12 text-center"
            style={{ borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.20))' }}
          >
            <p className="font-serif text-lg text-navy-800">No Offerings yet.</p>
            <p className="mt-1.5 text-sm text-black">
              Resources will appear here once they are published.
            </p>
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2">
            {cards.map((offering) => (
              <OfferingCard
                key={offering.id}
                offering={offering}
                spaceSlug={slug}
              />
            ))}
          </div>
        )}

        {/* Said once per page, not once per card. Every cover shows a
            physical-looking object because the artwork is illustrative,
            and a visitor scanning a grid of tablets and headphones
            should meet this sentence without having to open anything. */}
        {cards.length > 0 && (
          <p
            className="mt-6 text-[12.5px] italic leading-relaxed"
            style={{ color: 'rgba(12,24,38,0.55)' }}
          >
            Everything here is a digital download. Cover images are
            illustrations — any objects shown are not included, and
            nothing physical is posted to you.
          </p>
        )}
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
