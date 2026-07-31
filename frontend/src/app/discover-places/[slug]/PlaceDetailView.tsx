'use client'

import Link from 'next/link'
import { resolveMediaUrl } from '@/lib/api'
import {
  atmosphereBackground,
  atmosphereForSlug,
} from '@/lib/placeAtmosphere'
import CollectiveCard from '@/components/explore/CollectiveCard'
import { toSpaceWithMeta } from '@/components/explore/spaceMeta'
import type {
  PublicPlaceDetail,
  PublicPlaceGathering,
} from '@/lib/physicalLocations/types'

const COUNTRY_NAMES: Record<string, string> = {
  AU: 'Australia',
  NZ: 'New Zealand',
  GB: 'United Kingdom',
  US: 'United States',
  CA: 'Canada',
  IE: 'Ireland',
}

function countryName(code: string): string {
  return COUNTRY_NAMES[code.toUpperCase()] ?? code.toUpperCase()
}

/**
 * Member-facing detail view for a single Physical Location.
 *
 * Composition:
 *
 *   1. Location hero — the location's OWN artwork with its stored
 *      focal point, name, region + country, and admin-authored
 *      editorial blurb. Deterministic atmosphere gradient fallback
 *      when no artwork is uploaded.
 *   2. Collectives — rendered with the shared ``CollectiveCard`` used
 *      by Explore Collectives. Each card carries the Collective's own
 *      artwork + identity; the location's artwork never leaks here.
 *   3. Upcoming Gatherings — public / effectively-public events on
 *      those Collectives. Omitted entirely when there are none.
 */
export default function PlaceDetailView({ place }: { place: PublicPlaceDetail }) {
  return (
    <article>
      <PlaceHero place={place} />

      <div className="mx-auto w-full max-w-6xl px-6 md:px-10">
        <CollectivesSection place={place} />
        <GatheringsSection gatherings={place.upcoming_gatherings} />
      </div>
    </article>
  )
}

// ---------------------------------------------------------------------------
// Hero — location artwork lives ONLY here.
// ---------------------------------------------------------------------------

function PlaceHero({ place }: { place: PublicPlaceDetail }) {
  const artworkUrl = resolveMediaUrl(place.hero_artwork_url)
  const focalX = place.artwork_focal_x ?? 0.5
  const focalY = place.artwork_focal_y ?? 0.5

  return (
    <header className="relative isolate">
      <div className="relative h-[280px] w-full overflow-hidden md:h-[360px]">
        {artworkUrl ? (
          <div
            role={place.artwork_alt_text ? 'img' : undefined}
            aria-label={place.artwork_alt_text ?? undefined}
            aria-hidden={place.artwork_alt_text ? undefined : 'true'}
            className="absolute inset-0 h-full w-full bg-cover"
            style={{
              backgroundImage: `url("${artworkUrl}")`,
              backgroundPosition: `${focalX * 100}% ${focalY * 100}%`,
            }}
          />
        ) : (
          <div
            aria-hidden="true"
            className="absolute inset-0 h-full w-full"
            style={{
              background: atmosphereBackground(atmosphereForSlug(place.slug, false)),
            }}
          />
        )}
        {/* Legibility scrim */}
        <div
          aria-hidden="true"
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(to top, rgba(7,24,36,0.72) 0%, rgba(7,24,36,0.28) 45%, rgba(7,24,36,0.08) 100%)',
          }}
        />
        <div className="absolute inset-x-0 bottom-0 px-6 pb-8 md:px-10">
          <div className="mx-auto w-full max-w-6xl">
            <Link
              href="/discover-places"
              className="mb-3 inline-flex items-center text-[12.5px] font-medium text-white/85 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent"
            >
              ← Discover Places
            </Link>
            <h1 className="font-serif text-[36px] leading-tight text-white md:text-[48px]">
              {place.name}
            </h1>
            <p className="mt-1 text-[13.5px] text-white/85">
              {[place.region, countryName(place.country_code)].filter(Boolean).join(', ')}
            </p>
          </div>
        </div>
      </div>

      {place.blurb && (
        <div className="border-b border-slate-100 bg-white">
          <div className="mx-auto w-full max-w-3xl px-6 py-8 md:px-10 md:py-10">
            <p
              className="text-[16px] leading-relaxed text-navy-800"
              style={{ fontFamily: 'Georgia, serif' }}
            >
              {place.blurb}
            </p>
          </div>
        </div>
      )}
    </header>
  )
}

// ---------------------------------------------------------------------------
// Collectives — reuses the Explore Collectives card visual.
// ---------------------------------------------------------------------------

function CollectivesSection({ place }: { place: PublicPlaceDetail }) {
  const heading = place.collectives.length === 1
    ? `1 Collective in ${place.name}`
    : `${place.collectives.length} Collectives in ${place.name}`

  return (
    <section aria-labelledby="place-collectives-heading" className="py-10 md:py-14">
      <div className="mb-6 md:mb-8">
        <h2
          id="place-collectives-heading"
          className="font-serif text-[24px] leading-tight text-navy-900 md:text-[28px]"
        >
          {heading}
        </h2>
        {place.collectives.length === 0 && (
          <p
            className="mt-3 font-serif text-[15px] italic leading-relaxed text-navy-500"
          >
            No Collectives are gathering here yet — this location is
            just beginning to take root.
          </p>
        )}
      </div>

      {place.collectives.length > 0 && (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {place.collectives.map((c) => (
            <CollectiveCard
              key={c.id}
              space={toSpaceWithMeta(c)}
              isJoined={false}
              isLoggedIn={false}
            />
          ))}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Gatherings
// ---------------------------------------------------------------------------

function GatheringsSection({ gatherings }: { gatherings: PublicPlaceGathering[] }) {
  if (gatherings.length === 0) return null

  return (
    <section
      aria-labelledby="place-gatherings-heading"
      className="border-t border-slate-100 py-10 md:py-14"
    >
      <div className="mb-6 md:mb-8">
        <h2
          id="place-gatherings-heading"
          className="font-serif text-[24px] leading-tight text-navy-900 md:text-[28px]"
        >
          Upcoming Gatherings
        </h2>
        <p className="mt-1.5 text-[13.5px] text-navy-500">
          {gatherings.length === 1
            ? '1 upcoming Gathering'
            : `${gatherings.length} upcoming Gatherings`}
        </p>
      </div>

      <ul className="divide-y divide-slate-100">
        {gatherings.map((g) => (
          <GatheringRow key={g.id} gathering={g} />
        ))}
      </ul>
    </section>
  )
}

function GatheringRow({ gathering }: { gathering: PublicPlaceGathering }) {
  const when = formatWhen(gathering.starts_at, gathering.ends_at)
  const format = formatAttendance(gathering)

  return (
    <li className="py-5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="font-serif text-[18px] leading-snug text-navy-900">
          {gathering.title}
        </p>
        <p className="text-[12.5px] text-navy-500">
          {gathering.space_name}
        </p>
      </div>
      <p className="mt-1.5 text-[13px] text-navy-600">
        {when} · {format}
      </p>
    </li>
  )
}

function formatWhen(startsAt: string, endsAt: string | null): string {
  const start = new Date(startsAt)
  const dateStr = start.toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
  const timeStr = start.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
  if (endsAt) {
    const end = new Date(endsAt)
    const endTimeStr = end.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    })
    return `${dateStr}, ${timeStr}–${endTimeStr}`
  }
  return `${dateStr}, ${timeStr}`
}

function formatAttendance(g: PublicPlaceGathering): string {
  if (g.attendance_format === 'online') return 'Online'
  const label = g.attendance_format === 'hybrid' ? 'Hybrid' : 'In person'
  return g.venue_name ? `${label} · ${g.venue_name}` : label
}
