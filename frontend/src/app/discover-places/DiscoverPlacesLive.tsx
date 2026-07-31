'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { resolveMediaUrl } from '@/lib/api'
import {
  atmosphereBackground,
  atmosphereForSlug,
} from '@/lib/placeAtmosphere'
import { COLLECTIVE_THEMES } from '@/lib/themes'
import type { PublicPlaceSummary } from '@/lib/physicalLocations/types'

/**
 * Discover Places — the real member-facing surface, backed by
 * ``/api/places``.
 *
 * Only active Physical Locations reach here (the API filters out
 * draft / hidden / archived rows on the server). Draft, hidden and
 * archived Locations are never surfaced publicly.
 *
 * Card contents:
 *   * Curated hero artwork with its stored focal point + alt text
 *     when present; deterministic atmospheric gradient fallback
 *     otherwise.
 *   * Location name, region, country.
 *   * Admin-authored editorial blurb.
 *   * Aggregate theme chips + Collective / gathering counts sourced
 *     from linked active Collectives.
 *
 * The prototype scale selector is gone from this route. The prototype
 * fixtures still live under ``_prototype/`` for isolated design
 * review, but the live page never touches them.
 */

// ISO 3166-1 alpha-2 → member-facing country name. Small on purpose —
// only the countries that actually appear in the seed. The raw code
// is a safe visual fallback if a new country slips in before this map
// is extended.
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

// Locale-aware sort, matches the prototype's alphabetical ordering.
function byName(a: PublicPlaceSummary, b: PublicPlaceSummary) {
  return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
}

export default function DiscoverPlacesLive({
  places,
}: {
  places: PublicPlaceSummary[]
}) {
  const [search, setSearch] = useState('')
  const [activeThemes, setActiveThemes] = useState<string[]>([])

  const availableThemes = useMemo(() => {
    const seen = new Set<string>()
    for (const p of places) for (const t of p.themes) seen.add(t)
    // Keep the canonical theme ordering from lib/themes so filter
    // chips render in the same sequence used across the platform.
    return COLLECTIVE_THEMES.filter((t) => seen.has(t))
  }, [places])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return places
      .filter((p) => {
        if (q) {
          const inName = p.name.toLowerCase().includes(q)
          const inRegion = (p.region ?? '').toLowerCase().includes(q)
          if (!inName && !inRegion) return false
        }
        if (activeThemes.length > 0 && !p.themes.some((t) => activeThemes.includes(t))) {
          return false
        }
        return true
      })
      .slice()
      .sort(byName)
  }, [places, search, activeThemes])

  const isFiltering = search.trim().length > 0 || activeThemes.length > 0
  const showControls = places.length > 3

  if (places.length === 0) {
    return (
      <div className="mx-auto w-full max-w-6xl px-6 py-16 md:px-10">
        <p className="max-w-md font-serif italic text-navy-500">
          Fresh Collective communities are just beginning to take root
          — check back soon.
        </p>
      </div>
    )
  }

  return (
    <div className="pb-24">
      <div className="mx-auto w-full max-w-6xl px-6 md:px-10 pt-8 md:pt-10">
        {showControls && (
          <section aria-label="Discover controls" className="mb-8 space-y-4 md:mb-10">
            <div className="max-w-md">
              <label htmlFor="place-search" className="sr-only">
                Search Places by name or region
              </label>
              <input
                id="place-search"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search Places"
                className="w-full rounded-xl border border-slate-200 bg-white/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {availableThemes.length > 0 && (
              <ThemeFilters
                themes={availableThemes}
                active={activeThemes}
                onToggle={(theme) =>
                  setActiveThemes((prev) =>
                    prev.includes(theme) ? prev.filter((t) => t !== theme) : [...prev, theme],
                  )
                }
                onClear={() => setActiveThemes([])}
              />
            )}

            {isFiltering && (
              <p aria-live="polite" className="text-[13px] text-navy-500">
                {filtered.length} {filtered.length === 1 ? 'Place' : 'Places'} match.
              </p>
            )}
          </section>
        )}

        {filtered.length === 0 ? (
          <p className="mt-8 max-w-md font-serif italic text-navy-500">
            Nothing matches — try a different search or theme.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((p) => (
              <PlaceCard key={p.slug} place={p} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Theme filter chips
// ---------------------------------------------------------------------------

function ThemeFilters({
  themes, active, onToggle, onClear,
}: {
  themes: readonly string[]
  active: string[]
  onToggle: (theme: string) => void
  onClear: () => void
}) {
  return (
    <div>
      <span className="mb-2 block text-[12px] uppercase tracking-[0.06em] text-slate-500">
        Filter by theme
      </span>
      <div role="group" aria-label="Filter by theme" className="flex flex-wrap items-center gap-2">
        {themes.map((theme) => {
          const selected = active.includes(theme)
          return (
            <button
              key={theme}
              type="button"
              aria-pressed={selected}
              onClick={() => onToggle(theme)}
              className={
                'rounded-lg border px-3 py-1 text-[12px] transition-colors '
                + 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#38A09E]/40 focus-visible:ring-offset-2 '
                + (selected
                  ? 'border-[#38A09E]/60 bg-[#38A09E]/10 text-[#1E6E6C] font-semibold hover:bg-[#38A09E]/15'
                  : 'border-slate-200 text-slate-500 font-medium hover:border-slate-300 hover:bg-slate-50 hover:text-navy-900')
              }
            >
              {theme}
            </button>
          )
        })}
        {active.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="ml-1 rounded-lg px-2 py-1 text-[12px] text-slate-500 underline underline-offset-2 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function PlaceCard({ place }: { place: PublicPlaceSummary }) {
  const artworkUrl = resolveMediaUrl(place.hero_artwork_url)
  const focalX = place.artwork_focal_x ?? 0.5
  const focalY = place.artwork_focal_y ?? 0.5

  return (
    <Link
      href={`/discover-places/${place.slug}`}
      aria-labelledby={`place-${place.slug}-name`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white transition-shadow hover:shadow-[0_8px_24px_rgba(12,24,38,0.06)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 focus-visible:ring-offset-2"
    >
      {artworkUrl ? (
        <div
          role={place.artwork_alt_text ? 'img' : undefined}
          aria-label={place.artwork_alt_text ?? undefined}
          aria-hidden={place.artwork_alt_text ? undefined : 'true'}
          className="h-32 bg-cover"
          style={{
            backgroundImage: `url("${artworkUrl}")`,
            backgroundPosition: `${focalX * 100}% ${focalY * 100}%`,
          }}
        />
      ) : (
        <div
          aria-hidden="true"
          className="h-32"
          style={{
            background: atmosphereBackground(atmosphereForSlug(place.slug, false)),
          }}
        />
      )}

      <div className="flex flex-1 flex-col p-5">
        <h3
          id={`place-${place.slug}-name`}
          className="font-serif text-[20px] leading-tight text-navy-900"
        >
          {place.name}
        </h3>
        <p className="mt-0.5 text-[13px] text-navy-500">
          {[place.region, countryName(place.country_code)].filter(Boolean).join(', ')}
        </p>

        {place.blurb && (
          <p className="mt-3 text-[14px] leading-relaxed text-navy-700"
             style={{ fontFamily: 'Georgia, serif' }}>
            {place.blurb}
          </p>
        )}

        {place.themes.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {place.themes.slice(0, 4).map((t) => (
              <span
                key={t}
                className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-navy-600"
              >
                {t}
              </span>
            ))}
          </div>
        )}

        <p className="mt-4 text-[12.5px] text-navy-500">
          {activityLine(place.collective_count, place.upcoming_gathering_count)}
        </p>
      </div>
    </Link>
  )
}

function activityLine(collectives: number, gatherings: number): string {
  const parts: string[] = []
  if (collectives === 0) {
    parts.push('No Collectives here yet')
  } else if (collectives === 1) {
    parts.push('1 Collective')
  } else {
    parts.push(`${collectives} Collectives`)
  }
  if (gatherings > 0) {
    parts.push(gatherings === 1 ? '1 upcoming gathering' : `${gatherings} upcoming gatherings`)
  }
  return parts.join(' · ')
}
