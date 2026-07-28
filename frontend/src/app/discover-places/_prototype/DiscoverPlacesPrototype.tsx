'use client'

/**
 * PROTOTYPE — Discover Places
 * ============================================================
 *
 * TEMPORARY. Delete this whole `_prototype` folder when the real
 * Discover Places page ships. See ../page.tsx for the mount point
 * and ./mockData.ts for the fixture.
 *
 * Purpose: let us feel the shape of Discover Places in the browser
 * — hierarchy, browsing behaviour, card treatment, and how the
 * experience holds up as the world grows from a handful of Places
 * to sixty.
 *
 * Not connected to /api/places, the database, or any real Place
 * model. Nothing here should be treated as production code.
 */

import { useMemo, useState } from 'react'
import { COLLECTIVE_THEMES } from '@/lib/themes'
import {
  EARLY_WORLD,
  ESTABLISHED_WORLD,
  GROWING_WORLD,
  type PlaceMock,
} from './mockData'

type Scale = 'early' | 'growing' | 'established'

const SCALE_LABEL: Record<Scale, string> = {
  early:       'Early world',
  growing:     'Growing world',
  established: 'Established world',
}

const SCALE_SET: Record<Scale, PlaceMock[]> = {
  early:       EARLY_WORLD,
  growing:     GROWING_WORLD,
  established: ESTABLISHED_WORLD,
}

// ---------------------------------------------------------------------------
// Deterministic gradient palette for the card headers.
// Each Place gets a stable "atmosphere" derived from its slug, so cards feel
// individual without becoming visually noisy. Emerging Places use a slightly
// softer variant; not-yet-active Places wash out entirely.
// ---------------------------------------------------------------------------

interface Gradient { from: string; to: string }

const ATMOSPHERES: Gradient[] = [
  { from: '#B5D9D5', to: '#8FC0BB' },   // coastal teal
  { from: '#E8DFD3', to: '#D9CDB8' },   // warm sand
  { from: '#C8D6B8', to: '#A6BC97' },   // sage
  { from: '#B8C4D6', to: '#8AA0BB' },   // dusk navy
  { from: '#E8CFC5', to: '#D5AE9F' },   // rose clay
  { from: '#C4CED5', to: '#9EABB6' },   // slate blue
  { from: '#E8D9AE', to: '#D0BF87' },   // pale ochre
]

const QUIET_ATMOSPHERE: Gradient = { from: '#EEF1F4', to: '#DDE3EA' }

function atmosphereFor(place: PlaceMock): Gradient {
  if (place.activity === 'not_yet_active') return QUIET_ATMOSPHERE
  // Simple char-sum hash — stable across renders, good enough for a
  // prototype palette assignment.
  let hash = 0
  for (let i = 0; i < place.slug.length; i++) hash += place.slug.charCodeAt(i)
  const pick = ATMOSPHERES[hash % ATMOSPHERES.length]
  if (place.activity === 'emerging') {
    // Fade the palette a touch so emerging Places feel gentler.
    return { from: mixWithWhite(pick.from, 0.35), to: mixWithWhite(pick.to, 0.35) }
  }
  return pick
}

function mixWithWhite(hex: string, ratio: number): string {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 0xff
  const g = (n >> 8) & 0xff
  const b = n & 0xff
  const mix = (c: number) => Math.round(c + (255 - c) * ratio)
  return `#${((1 << 24) + (mix(r) << 16) + (mix(g) << 8) + mix(b)).toString(16).slice(1)}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DiscoverPlacesPrototype() {
  const [scale, setScale]                 = useState<Scale>('early')
  const [search, setSearch]               = useState('')
  const [activeThemes, setActiveThemes]   = useState<string[]>([])
  const [groupByState, setGroupByState]   = useState(false)

  const allPlaces = SCALE_SET[scale]

  // Progressive-disclosure rules — the small state deliberately does
  // NOT show controls, because four Places should never feel like they
  // require a directory interface.
  const showSearch   = scale !== 'early'
  const showFilters  = scale !== 'early'
  const showGrouping = scale === 'established'

  // Reset scale-scoped filters when the scale changes so the review
  // control never leaves behind a stale filter state.
  function handleScaleChange(next: Scale) {
    setScale(next)
    setSearch('')
    setActiveThemes([])
    setGroupByState(false)
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allPlaces.filter((p) => {
      if (q && !p.name.toLowerCase().includes(q)) return false
      if (activeThemes.length > 0 && !p.themes.some((t) => activeThemes.includes(t))) return false
      return true
    })
  }, [allPlaces, search, activeThemes])

  const isFiltering = search.trim().length > 0 || activeThemes.length > 0

  // Themes present anywhere in the current scale — the filter row
  // shouldn't offer themes that no Place at this scale carries.
  const availableThemes = useMemo(() => {
    const set = new Set<string>()
    for (const p of allPlaces) for (const t of p.themes) set.add(t)
    return COLLECTIVE_THEMES.filter((t) => set.has(t))
  }, [allPlaces])

  return (
    <div className="pb-24">
      <ScaleReviewControl scale={scale} onChange={handleScaleChange} />

      <div className="mx-auto w-full max-w-6xl px-6 md:px-10 pt-10 md:pt-16">
        {/* ── Page introduction ── */}
        <header className="mb-10 md:mb-14 max-w-2xl">
          <h1 className="mb-3 font-serif text-3xl text-navy-900 md:text-4xl">
            Discover Places
          </h1>
          <p className="font-serif text-lg italic leading-relaxed text-navy-600">
            Explore the places where Fresh Collective communities are growing.
          </p>
        </header>

        {/* ── Controls ── */}
        {(showSearch || showFilters) && (
          <section
            aria-label="Discover controls"
            className="mb-8 space-y-4 md:mb-10"
          >
            {showSearch && (
              <div className="max-w-md">
                <label htmlFor="place-search" className="sr-only">
                  Search Places by name
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
            )}

            {showFilters && availableThemes.length > 0 && (
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

            {showGrouping && (
              <div className="flex items-center gap-3 text-[13px] text-navy-500">
                <label className="inline-flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={groupByState}
                    onChange={(e) => setGroupByState(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-400/30"
                  />
                  <span>Group by state</span>
                </label>
              </div>
            )}

            {isFiltering && (
              <p
                aria-live="polite"
                className="text-[13px] text-navy-500"
              >
                {filtered.length}
                {' '}
                {filtered.length === 1 ? 'Place' : 'Places'}
                {' '}
                match.
              </p>
            )}
          </section>
        )}

        {/* ── Card grid (or grouped grid) ── */}
        {groupByState && showGrouping
          ? <GroupedPlaces places={filtered} />
          : <PlaceGrid  places={filtered} />}
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Scale review control — clearly a design tool, not a member feature.
// ---------------------------------------------------------------------------

function ScaleReviewControl({
  scale,
  onChange,
}: {
  scale: Scale
  onChange: (s: Scale) => void
}) {
  const scales: Scale[] = ['early', 'growing', 'established']
  return (
    <div
      role="region"
      aria-label="Prototype scale review control"
      className="border-b border-dashed border-slate-300 bg-slate-50/60"
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-6 py-3 md:flex-row md:items-center md:gap-4 md:px-10">
        <span className="text-[11px] uppercase tracking-[0.08em] text-slate-500">
          Prototype control · not a member-facing feature
        </span>
        <div role="group" aria-label="Choose prototype scale" className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1">
          {scales.map((s) => {
            const selected = s === scale
            return (
              <button
                key={s}
                type="button"
                aria-pressed={selected}
                onClick={() => onChange(s)}
                className={
                  'rounded-md px-3 py-1 text-[12px] transition-colors ' +
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ' +
                  (selected
                    ? 'bg-navy-900 text-white font-medium'
                    : 'text-slate-600 hover:text-navy-900 hover:bg-slate-50')
                }
              >
                {SCALE_LABEL[s]}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Theme filter chips
// ---------------------------------------------------------------------------

function ThemeFilters({
  themes,
  active,
  onToggle,
  onClear,
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
                'rounded-lg border px-3 py-1 text-[12px] transition-colors ' +
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#38A09E]/40 focus-visible:ring-offset-2 ' +
                (selected
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
// Grid
// ---------------------------------------------------------------------------

function PlaceGrid({ places }: { places: PlaceMock[] }) {
  if (places.length === 0) {
    return (
      <p className="mt-8 max-w-md font-serif italic text-navy-500">
        Nothing matches — try a different search or theme.
      </p>
    )
  }
  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {places.map((p) => (
        <PlaceCard key={p.slug} place={p} />
      ))}
    </div>
  )
}

function GroupedPlaces({ places }: { places: PlaceMock[] }) {
  const stateOrder = ['VIC', 'NSW', 'QLD', 'TAS', 'SA', 'WA', 'NT', 'ACT'] as const
  // Preserve stateOrder order, drop empty groups.
  const groups = stateOrder
    .map((code) => ({
      code,
      label: places.find((p) => p.stateCode === code)?.region ?? code,
      items: places.filter((p) => p.stateCode === code),
    }))
    .filter((g) => g.items.length > 0)

  if (groups.length === 0) {
    return (
      <p className="mt-8 max-w-md font-serif italic text-navy-500">
        Nothing matches — try a different search or theme.
      </p>
    )
  }

  return (
    <div className="space-y-10">
      {groups.map((g) => (
        <section key={g.code} aria-labelledby={`state-${g.code}`}>
          <h2
            id={`state-${g.code}`}
            className="mb-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-navy-500"
          >
            {g.label}
          </h2>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {g.items.map((p) => (
              <PlaceCard key={p.slug} place={p} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function PlaceCard({ place }: { place: PlaceMock }) {
  const atmosphere = atmosphereFor(place)
  const quiet      = place.activity === 'not_yet_active'

  return (
    <article
      aria-labelledby={`place-${place.slug}-name`}
      className={
        'group flex flex-col overflow-hidden rounded-2xl border bg-white transition-shadow ' +
        (quiet
          ? 'border-slate-200/70'
          : 'border-slate-200 hover:shadow-[0_8px_24px_rgba(12,24,38,0.06)]')
      }
    >
      {/* Atmosphere header — deterministic gradient */}
      <div
        aria-hidden="true"
        className="h-20"
        style={{ background: `linear-gradient(135deg, ${atmosphere.from}, ${atmosphere.to})` }}
      />

      {/* Body */}
      <div className="flex flex-1 flex-col p-5">
        <h3
          id={`place-${place.slug}-name`}
          className={
            'font-serif text-[20px] leading-tight ' +
            (quiet ? 'text-navy-600' : 'text-navy-900')
          }
        >
          {place.name}
        </h3>
        <p className="mt-0.5 text-[13px] text-navy-500">{place.region}</p>

        {place.activity === 'not_yet_active' ? (
          <p className="mt-5 font-serif italic text-[14px] leading-relaxed text-navy-500">
            Fresh Collective has not taken root here yet.
          </p>
        ) : (
          <>
            <p className="mt-4 font-serif italic text-[14px] leading-relaxed text-navy-600">
              {place.livingIdentity}
            </p>

            {place.themes.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {place.themes.map((t) => (
                  <span
                    key={t}
                    className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-navy-600"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}

            <dl className="mt-5 flex items-center gap-5 text-[13px] text-navy-600">
              <div>
                <dt className="sr-only">Active Collectives</dt>
                <dd>
                  <span className="font-semibold text-navy-900">
                    {place.activeCollectives}
                  </span>{' '}
                  {place.activeCollectives === 1 ? 'Collective' : 'Collectives'}
                </dd>
              </div>
              <div>
                <dt className="sr-only">Upcoming Gatherings</dt>
                <dd>
                  <span className="font-semibold text-navy-900">
                    {place.upcomingGatherings}
                  </span>{' '}
                  upcoming {place.upcomingGatherings === 1 ? 'Gathering' : 'Gatherings'}
                </dd>
              </div>
            </dl>
          </>
        )}
      </div>
    </article>
  )
}
