import Link from 'next/link'
import { getAdminLocations } from '@/lib/serverApi'
import type { LocationSummary } from '@/lib/atlas/types'
import LocationArtwork from '@/components/admin/atlas/LocationArtwork'

/**
 * The Atlas — a curated collection of Locations.
 *
 * Split into three sections:
 *   Cornerstones        — reserved for Fresh Collective experiences.
 *   Atlas Locations     — premium worlds for Creator and Pro collectives.
 *   Community Locations — intimate gathering places for Community (Free)
 *                         collectives.
 *
 * Card design is shared; ordering is global across sections (position),
 * so a Cornerstone with a lower position sits at the top of its section
 * exactly as an Atlas Location would within its own.
 */
export default async function AtlasIndexPage() {
  const locations: LocationSummary[] = await getAdminLocations()
  const cornerstones = locations.filter((l) => l.location_type === 'CORNERSTONE')
  const atlas = locations.filter((l) => l.location_type === 'ATLAS')
  const community = locations.filter((l) => l.location_type === 'COMMUNITY')

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
      {/* Header */}
      <header className="mb-12 flex flex-wrap items-end justify-between gap-6">
        <div>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em]"
            style={{ color: '#38A09E' }}
          >
            Fresh Collective
          </p>
          <h1
            className="font-serif text-[32px] leading-tight md:text-[40px]"
            style={{ color: '#0C1826' }}
          >
            The Atlas
          </h1>
          <p
            className="mt-3 max-w-[560px] text-[15px] leading-relaxed italic"
            style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
          >
            A curated collection of the Locations that make up the Fresh Collective world. Every collective lives inside one of these.
          </p>
        </div>
        <Link
          href="/admin/atlas/new"
          className="rounded-full px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            letterSpacing: '0.06em',
          }}
        >
          + Add a Location
        </Link>
      </header>

      {/* Cornerstones */}
      <Section
        title="Cornerstones"
        description="The foundational Locations of the Fresh Collective world. Reserved for Fresh Collective experiences."
        emptyMessage="No Cornerstones yet."
        locations={cornerstones}
      />

      {/* Atlas Locations */}
      <Section
        title="Atlas Locations"
        description="Premium worlds available to Creator and Pro collectives."
        emptyMessage="No Atlas Locations yet. Add one so creators have a home to choose."
        locations={atlas}
      />

      {/* Community Locations */}
      <Section
        title="Community Locations"
        description="Simple places where new communities begin."
        emptyMessage="No Community Locations yet."
        locations={community}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------

function Section({
  title, description, emptyMessage, locations,
}: {
  title: string
  description: string
  emptyMessage: string
  locations: LocationSummary[]
}) {
  return (
    <section className="mb-14 last:mb-0">
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h2
            className="font-serif text-[22px] leading-tight md:text-[26px]"
            style={{ color: '#0C1826' }}
          >
            {title}
          </h2>
          <p
            className="mt-1.5 max-w-[560px] text-[13.5px] italic leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
          >
            {description}
          </p>
        </div>
        <p className="text-[12px]" style={{ color: 'rgba(12, 24, 38, 0.50)' }}>
          {locations.length === 1 ? '1 Location' : `${locations.length} Locations`}
        </p>
      </div>

      {locations.length > 0 ? (
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {locations.map((loc) => (
            <LocationCard key={loc.key} loc={loc} />
          ))}
        </div>
      ) : (
        <div
          className="rounded-2xl bg-white p-8 text-center"
          style={{ border: '1px dashed rgba(12, 24, 38, 0.15)' }}
        >
          <p className="text-[13.5px] italic" style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}>
            {emptyMessage}
          </p>
        </div>
      )}
    </section>
  )
}

function LocationCard({ loc }: { loc: LocationSummary }) {
  return (
    <Link
      href={`/admin/atlas/${loc.key}`}
      className="group block overflow-hidden rounded-2xl bg-white transition-all"
      style={{
        border: '1px solid rgba(12, 24, 38, 0.06)',
        boxShadow: '0 6px 20px rgba(12, 24, 38, 0.06)',
      }}
    >
      <div
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: '3 / 2', background: '#F4F7F6' }}
      >
        <LocationArtwork
          url={loc.thumbnail_artwork_url ?? loc.hero_artwork_url}
          label={loc.name}
          fit="cover"
          className="h-full w-full transition-transform duration-500 group-hover:scale-[1.02]"
        />
        {loc.status === 'hidden' && (
          <span
            className="absolute right-3 top-3 rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wide"
            style={{
              background: 'rgba(255,255,255,0.92)',
              color: 'rgba(12,24,38,0.62)',
              backdropFilter: 'blur(6px)',
            }}
          >
            Hidden
          </span>
        )}
      </div>

      <div className="px-6 pt-5 pb-6">
        <h3
          className="font-serif text-[20px] leading-tight"
          style={{ color: '#0C1826' }}
        >
          {loc.name}
        </h3>
        {loc.description && (
          <p
            className="mt-2 line-clamp-2 text-[13.5px] leading-relaxed italic"
            style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
          >
            {loc.description}
          </p>
        )}
        <p
          className="mt-4 text-[12px]"
          style={{ color: 'rgba(12, 24, 38, 0.50)' }}
        >
          {loc.collective_count === 0
            ? 'No collectives living here yet'
            : loc.collective_count === 1
            ? '1 collective lives here'
            : `${loc.collective_count} collectives live here`}
        </p>
      </div>
    </Link>
  )
}
