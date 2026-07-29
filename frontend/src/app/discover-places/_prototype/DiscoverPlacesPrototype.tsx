'use client'

/**
 * PROTOTYPE — Discover Places (iteration 2)
 * ============================================================
 *
 * TEMPORARY. Delete this whole `_prototype` folder when the real
 * Discover Places page ships. See ../page.tsx for the mount point
 * and ./mockData.ts for the fixture.
 *
 * The prompt for this iteration: "Does Discover Places feel like
 * exploring a living world rather than browsing a directory?"
 *
 * What changed from iteration 1:
 *
 *   * Community becomes the hero, geography the setting.
 *     Heading, intro copy and card treatment lead with what
 *     community life is happening here, not with names of towns.
 *
 *   * Numeric metrics ("8 Collectives · 23 Gatherings") are gone.
 *     In their place, each card carries a warm character line
 *     derived from the Place's tier and top themes — e.g.
 *     "Weekly gatherings across Wellbeing, Creativity and
 *     Leadership." Numbers still live on the fixture so the tier
 *     can be derived, but they are never surfaced.
 *
 *   * Not-yet-active Places are removed entirely (from the
 *     fixture, from the prototype). Discover Places celebrates
 *     where community already lives; it does not name absence.
 *
 *   * State labels are hidden for well-known major cities
 *     (Melbourne, Sydney, Brisbane, Perth, Adelaide, Hobart,
 *     Canberra, Darwin) — "Melbourne" is enough on its own.
 *     Smaller Places still show their state.
 *
 *   * At Established scale, the flat card grid becomes a
 *     narrative — three sections telling the story of the world:
 *     Flourishing communities → Growing communities →
 *     Emerging communities. When the reader searches or filters,
 *     the sections collapse back into a single grid because the
 *     narrative is theirs, not the page's.
 *
 *   * The atmosphere header is a touch taller and gains a soft
 *     morning-light highlight so each Place has slightly more
 *     presence, without introducing icons, illustrations or
 *     imagery.
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
type Tier  = 'flourishing' | 'growing' | 'emerging'

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

// Well-known major cities where the state name adds noise more than
// context. For every other Place the region still appears — "Byron
// Bay, New South Wales" reads naturally; "Melbourne, Victoria" adds
// nothing a member doesn't already know.
const MAJOR_CITIES = new Set<string>([
  'Melbourne', 'Sydney', 'Brisbane', 'Perth',
  'Adelaide', 'Hobart',   'Canberra', 'Darwin',
])

const TIER_META: Record<Tier, { label: string; subheading: string }> = {
  flourishing: {
    label:      'Flourishing communities',
    subheading: 'Where community life is in full bloom.',
  },
  growing: {
    label:      'Growing communities',
    subheading: 'Where the community is finding its rhythm.',
  },
  emerging: {
    label:      'Emerging communities',
    subheading: 'Where something new is beginning to take root.',
  },
}

// Colour atmospheres for the card header. Deterministic per slug so
// a Place keeps the same feel across every render.
interface Gradient { from: string; to: string }
const ATMOSPHERES: Gradient[] = [
  { from: '#B5D9D5', to: '#7AB6B1' },   // coastal teal
  { from: '#E8DFD3', to: '#C7B99C' },   // warm sand
  { from: '#C8D6B8', to: '#94AE83' },   // sage
  { from: '#B8C4D6', to: '#778EAA' },   // dusk navy
  { from: '#E8CFC5', to: '#C89A88' },   // rose clay
  { from: '#C4CED5', to: '#8896A2' },   // slate blue
  { from: '#E8D9AE', to: '#BFAA6A' },   // pale ochre
]

function atmosphereFor(place: PlaceMock): Gradient {
  let hash = 0
  for (let i = 0; i < place.slug.length; i++) hash += place.slug.charCodeAt(i)
  const pick = ATMOSPHERES[hash % ATMOSPHERES.length]
  if (place.activity === 'emerging') {
    // Emerging Places wash a little towards the light — softer,
    // less asserted — so tier reads visually as well as textually.
    return { from: mixWithWhite(pick.from, 0.25), to: mixWithWhite(pick.to, 0.25) }
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

// Tier derivation. Emerging is authored on the fixture; the two
// active tiers split on activeCollectives so the character line can
// speak with the right register.
function tierFor(place: PlaceMock): Tier {
  if (place.activity === 'emerging')   return 'emerging'
  if (place.activeCollectives >= 6)    return 'flourishing'
  return 'growing'
}

function joinThemes(themes: readonly string[], max: number): string {
  const picked = themes.slice(0, max)
  if (picked.length === 0) return ''
  if (picked.length === 1) return picked[0]
  if (picked.length === 2) return `${picked[0]} and ${picked[1]}`
  return `${picked.slice(0, -1).join(', ')} and ${picked[picked.length - 1]}`
}

// The single line each card leads with in place of raw counts.
// Tone matches the tier — busy and confident at flourishing, quiet
// and observant at emerging.
function characterLineFor(place: PlaceMock): string {
  const tier = tierFor(place)
  if (tier === 'flourishing') {
    return `Weekly gatherings across ${joinThemes(place.themes, 3)}.`
  }
  if (tier === 'growing') {
    return `Regular gatherings — ${joinThemes(place.themes, 2)}.`
  }
  // Emerging
  if (place.themes.length > 0) {
    return `A small community exploring ${joinThemes(place.themes, 2)}.`
  }
  return 'A small community, just beginning.'
}


// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

export default function DiscoverPlacesPrototype() {
  const [scale, setScale]               = useState<Scale>('early')
  const [search, setSearch]             = useState('')
  const [activeThemes, setActiveThemes] = useState<string[]>([])

  const allPlaces = SCALE_SET[scale]

  // Controls follow scale. Four cards should never look like they
  // need a directory interface; sixty should always support one.
  const showSearch  = scale !== 'early'
  const showFilters = scale !== 'early'

  function handleScaleChange(next: Scale) {
    setScale(next)
    setSearch('')
    setActiveThemes([])
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

  // Only offer theme filters that at least one visible Place carries.
  const availableThemes = useMemo(() => {
    const set = new Set<string>()
    for (const p of allPlaces) for (const t of p.themes) set.add(t)
    return COLLECTIVE_THEMES.filter((t) => set.has(t))
  }, [allPlaces])

  // Tier grouping is a narrative device — it should not compete
  // with an active filter, which is the reader's own narrative.
  const groupByTier = scale === 'established' && !isFiltering

  return (
    <div className="pb-24">
      <ScaleReviewControl scale={scale} onChange={handleScaleChange} />

      <div className="mx-auto w-full max-w-6xl px-6 md:px-10 pt-10 md:pt-16">
        {/* ── Page introduction ── */}
        <header className="mb-10 md:mb-14 max-w-2xl">
          <h1 className="mb-3 font-serif text-3xl text-navy-900 md:text-4xl">
            Where communities are growing
          </h1>
          <p className="font-serif text-lg italic leading-relaxed text-navy-600">
            The places where our communities are gathering, learning and belonging.
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

        {/* ── Card grid or narrative sections ── */}
        {groupByTier
          ? <TieredPlaces places={filtered} />
          : <PlaceGrid   places={filtered} />}
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
// Grid + tiered layout
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

function TieredPlaces({ places }: { places: PlaceMock[] }) {
  const order: Tier[] = ['flourishing', 'growing', 'emerging']
  const groups = order
    .map((tier) => ({
      tier,
      items: places.filter((p) => tierFor(p) === tier),
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
    <div className="space-y-12 md:space-y-16">
      {groups.map((g) => {
        const meta = TIER_META[g.tier]
        return (
          <section key={g.tier} aria-labelledby={`tier-${g.tier}`}>
            <header className="mb-5 md:mb-6 max-w-2xl">
              <h2
                id={`tier-${g.tier}`}
                className="font-serif text-[22px] text-navy-900 md:text-[24px]"
              >
                {meta.label}
              </h2>
              <p className="mt-1 font-serif italic text-[15px] leading-relaxed text-navy-500">
                {meta.subheading}
              </p>
            </header>
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {g.items.map((p) => (
                <PlaceCard key={p.slug} place={p} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function PlaceCard({ place }: { place: PlaceMock }) {
  const atmosphere = atmosphereFor(place)
  const showRegion = !MAJOR_CITIES.has(place.name)

  return (
    <article
      aria-labelledby={`place-${place.slug}-name`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white transition-shadow hover:shadow-[0_8px_24px_rgba(12,24,38,0.06)]"
    >
      {/* Atmosphere header — deterministic gradient with a soft
          morning-light highlight in the top-left. Slightly taller
          than iteration 1 to give each Place more presence. */}
      <div
        aria-hidden="true"
        className="relative h-24"
        style={{
          background: `linear-gradient(150deg, ${atmosphere.from}, ${atmosphere.to})`,
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse at 22% 22%, rgba(255,255,255,0.32), transparent 60%)',
          }}
        />
      </div>

      {/* Body */}
      <div className="flex flex-1 flex-col p-5">
        <h3
          id={`place-${place.slug}-name`}
          className="font-serif text-[20px] leading-tight text-navy-900"
        >
          {place.name}
        </h3>
        {showRegion && (
          <p className="mt-0.5 text-[13px] text-navy-500">{place.region}</p>
        )}

        <p className={
          'font-serif italic text-[14px] leading-relaxed text-navy-600 ' +
          (showRegion ? 'mt-4' : 'mt-3')
        }>
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

        {/* Character line — replaces the two-metric row. Sits at the
            bottom of the card so it reads as the closing note about
            what community life looks like here. */}
        <p className="mt-5 text-[13px] leading-relaxed text-navy-500">
          {characterLineFor(place)}
        </p>
      </div>
    </article>
  )
}
