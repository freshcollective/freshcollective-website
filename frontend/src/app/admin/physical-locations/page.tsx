import Link from 'next/link'
import { getAdminPhysicalLocations } from '@/lib/serverApi'
import type { PhysicalLocationSummary } from '@/lib/physicalLocations/types'
import PhysicalLocationsListClient from './PhysicalLocationsListClient'

interface PageProps {
  searchParams: Promise<{
    q?: string
    status?: string
    country?: string
    sort?: string
  }>
}

/**
 * Physical Locations — the admin catalogue of the real-world places
 * that back Discover Places.
 *
 * Sits alongside The Atlas in World Management: The Atlas is the
 * mythic worldview (Islands, Cornerstones) that gives Collectives
 * their identity; Physical Locations are the real-world cities and
 * regions where communities gather. A Collective may belong to a
 * Physical Location, but must never inherit its artwork.
 */
export default async function PhysicalLocationsIndexPage({ searchParams }: PageProps) {
  const sp = await searchParams
  const locations: PhysicalLocationSummary[] = await getAdminPhysicalLocations({
    q: sp.q,
    status: sp.status,
    country: sp.country,
    sort: sp.sort,
  })

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
      {/* Header */}
      <header className="mb-8 flex flex-wrap items-end justify-between gap-6">
        <div>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em]"
            style={{ color: '#38A09E' }}
          >
            World Management
          </p>
          <h1
            className="font-serif text-[32px] leading-tight md:text-[40px]"
            style={{ color: '#0C1826' }}
          >
            Physical Locations
          </h1>
          <p
            className="mt-3 max-w-[620px] text-[15px] leading-relaxed italic"
            style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
          >
            The broad discovery areas where Fresh Collective
            communities gather — cities and named regions members
            naturally search for. Kept separate from Collective
            visual identity and the mythic Atlas.
          </p>
          <p
            className="mt-2 max-w-[620px] text-[13px] leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.55)' }}
          >
            Think Melbourne, Hobart, or the Blue Mountains — not
            suburbs like Fitzroy or Croydon South. Specific
            localities belong on the Collective, and precise venues
            on the Gathering.
          </p>
        </div>
        <Link
          href="/admin/physical-locations/new"
          className="rounded-full px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            letterSpacing: '0.06em',
          }}
        >
          + Add a Physical Location
        </Link>
      </header>

      <PhysicalLocationsListClient
        initialLocations={locations}
        initialFilters={{
          q: sp.q ?? '',
          status: sp.status ?? '',
          country: sp.country ?? '',
          sort: (sp.sort as 'alphabetical' | 'recently-updated' | 'most-collectives') ?? 'alphabetical',
        }}
      />
    </div>
  )
}
