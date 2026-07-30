'use client'

/**
 * PROTOTYPE — Discover Places (iteration 3)
 * ============================================================
 *
 * TEMPORARY. Delete this whole `_prototype` folder when the real
 * Discover Places page ships. See ../page.tsx for the mount point
 * and ./mockData.ts for the fixture.
 *
 * The prompt for this iteration: "Does the page now feel scalable
 * without becoming a directory?"
 *
 * What changed from iteration 2:
 *
 *   * Every visible group of Places is sorted alphabetically by
 *     name — every scale, every tier, every filter, every search.
 *     Fixture order is not preserved. Alphabetical is calm and
 *     predictable.
 *
 *   * The Established view is now a collapsible tier accordion,
 *     not one long scroll. All three tier headers (Flourishing,
 *     Growing, Emerging) are visible near the top so the shape of
 *     the world is legible at a glance. Flourishing opens by
 *     default; Growing and Emerging start closed. Multiple can
 *     be open at once.
 *
 *   * When the reader searches or filters, the accordion
 *     collapses into a single flat alphabetical grid, and each
 *     card carries a subtle tier eyebrow so the activity
 *     character is not lost while filtered.
 *
 *   * State labels are no longer suppressed for major cities.
 *     Every card renders "Region, Country" consistently so
 *     international Places sit alongside Australian ones without
 *     visual jitter.
 *
 *   * A handful of international Places have been added to the
 *     Established fixture (Auckland, Bali, Edinburgh, Portland,
 *     Vancouver) to stress-test the design outside Australia.
 */

import { useMemo, useState } from 'react'
import { COLLECTIVE_THEMES } from '@/lib/themes'
import {
  atmosphereBackground,
  atmosphereForSlug,
} from '@/lib/placeAtmosphere'
import {
  EARLY_WORLD,
  ESTABLISHED_WORLD,
  GROWING_WORLD,
  type PlaceMock,
} from './mockData'

type Scale = 'early' | 'growing' | 'established'
type Tier  = 'flourishing' | 'growing' | 'emerging'

const SCALE_LABEL: Record<Scale, string> = {
  early:       'Early communities',
  growing:     'Growing communities',
  established: 'Established communities',
}

const SCALE_SET: Record<Scale, PlaceMock[]> = {
  early:       EARLY_WORLD,
  growing:     GROWING_WORLD,
  established: ESTABLISHED_WORLD,
}

// Tier metadata — subtle colour cue is the only visual identity
// carried between the section header and the filtered eyebrow. All
// three colours sit within Fresh Collective's calm palette; none is
// loud enough to dominate a card.
const TIER_META: Record<Tier, {
  label:      string
  subheading: string
  dot:        string
  pillBg:     string
  pillText:   string
}> = {
  flourishing: {
    label:      'Flourishing communities',
    subheading: 'Where community life is in full bloom.',
    dot:        '#38A09E',
    pillBg:     'rgba(56, 160, 158, 0.12)',
    pillText:   '#1E6E6C',
  },
  growing: {
    label:      'Growing communities',
    subheading: 'Where the community is finding its rhythm.',
    dot:        '#7EA87A',
    pillBg:     'rgba(126, 168, 122, 0.14)',
    pillText:   '#3D6B3B',
  },
  emerging: {
    label:      'Emerging communities',
    subheading: 'Where something new is beginning to take root.',
    dot:        '#C5A876',
    pillBg:     'rgba(197, 168, 118, 0.16)',
    pillText:   '#7A5E2E',
  },
}

// The atmospheric fallback palette lives in lib/placeAtmosphere.ts
// so it will outlive this prototype. Only the derivation call is
// local — we pass the Place's `emerging` flag so quieter tiers
// wash the palette towards white.

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

function characterLineFor(place: PlaceMock): string {
  const tier = tierFor(place)
  if (tier === 'flourishing') {
    return `Weekly gatherings across ${joinThemes(place.themes, 3)}.`
  }
  if (tier === 'growing') {
    return `Regular gatherings — ${joinThemes(place.themes, 2)}.`
  }
  if (place.themes.length > 0) {
    return `A small community exploring ${joinThemes(place.themes, 2)}.`
  }
  return 'A small community, just beginning.'
}

// Locale-aware, case-insensitive sort so "Adelaide" comes before
// "Adelaide Hills" and international names sort naturally.
function byName(a: PlaceMock, b: PlaceMock): number {
  return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
}


// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

export default function DiscoverPlacesPrototype() {
  const [scale, setScale]               = useState<Scale>('early')
  const [search, setSearch]             = useState('')
  const [activeThemes, setActiveThemes] = useState<string[]>([])

  const allPlaces = SCALE_SET[scale]

  const showSearch  = scale !== 'early'
  const showFilters = scale !== 'early'

  function handleScaleChange(next: Scale) {
    setScale(next)
    setSearch('')
    setActiveThemes([])
  }

  // Filter, then always sort alphabetically. `byName` is stable and
  // locale-aware, so this list is the single source of truth for
  // everything below.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allPlaces
      .filter((p) => {
        if (q && !p.name.toLowerCase().includes(q)) return false
        if (activeThemes.length > 0 && !p.themes.some((t) => activeThemes.includes(t))) return false
        return true
      })
      .slice()
      .sort(byName)
  }, [allPlaces, search, activeThemes])

  const isFiltering = search.trim().length > 0 || activeThemes.length > 0

  const availableThemes = useMemo(() => {
    const set = new Set<string>()
    for (const p of allPlaces) for (const t of p.themes) set.add(t)
    return COLLECTIVE_THEMES.filter((t) => set.has(t))
  }, [allPlaces])

  // Accordion applies only to Established, and only when the reader
  // is not filtering — a filtered/search state is the reader's own
  // narrative and does not need a tier gate in front of it.
  const useAccordion = scale === 'established' && !isFiltering

  return (
    <div className="pb-24">
      <ScaleReviewControl scale={scale} onChange={handleScaleChange} />

      <div className="mx-auto w-full max-w-6xl px-6 md:px-10 pt-8 md:pt-10">
        {/* The page-level heading now lives in the shared PageHero
            mounted by ../page.tsx above the ScaleReviewControl and
            this content. The prototype only owns its own controls
            and grid from here down. */}

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

        {/* ── Card grid or tier accordion ── */}
        {useAccordion
          ? <TierAccordion places={filtered} />
          : <PlaceGrid    places={filtered} showTier={isFiltering} />}
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
          Prototype scale · testing different community sizes
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
// Flat grid — used at Early, Growing, and Established-while-filtering.
// ---------------------------------------------------------------------------

function PlaceGrid({ places, showTier }: { places: PlaceMock[]; showTier?: boolean }) {
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
        <PlaceCard key={p.slug} place={p} showTier={showTier} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tier accordion — the Established view's calm, editorial gateway to the
// three tiers of community life. All three headers stay together at the top
// so the shape of the world is legible without scrolling.
// ---------------------------------------------------------------------------

function TierAccordion({ places }: { places: PlaceMock[] }) {
  // Default: Flourishing is open, Growing and Emerging are closed.
  // Multiple can be open at once — never single-open.
  const [openTiers, setOpenTiers] = useState<Set<Tier>>(
    () => new Set<Tier>(['flourishing']),
  )

  function toggle(tier: Tier) {
    setOpenTiers((prev) => {
      const next = new Set(prev)
      if (next.has(tier)) next.delete(tier)
      else next.add(tier)
      return next
    })
  }

  const order: Tier[] = ['flourishing', 'growing', 'emerging']
  const groups = order.map((tier) => ({
    tier,
    // `places` is already alphabetical, so filtering preserves order.
    items: places.filter((p) => tierFor(p) === tier),
  }))

  return (
    <div className="space-y-4 md:space-y-6">
      {groups.map((g) => {
        const meta      = TIER_META[g.tier]
        const isOpen    = openTiers.has(g.tier)
        const contentId = `tier-content-${g.tier}`
        const hasItems  = g.items.length > 0
        return (
          <section key={g.tier} aria-labelledby={`tier-header-${g.tier}`}>
            <button
              type="button"
              id={`tier-header-${g.tier}`}
              aria-expanded={isOpen}
              aria-controls={contentId}
              aria-disabled={!hasItems || undefined}
              onClick={() => hasItems && toggle(g.tier)}
              className={
                'group flex w-full items-start justify-between gap-4 rounded-xl px-3 py-4 text-left transition-colors ' +
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ' +
                (hasItems ? 'hover:bg-slate-50 cursor-pointer' : 'opacity-70 cursor-default')
              }
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span
                    aria-hidden="true"
                    className="inline-block h-2 w-2 shrink-0 rounded-full"
                    style={{ background: meta.dot }}
                  />
                  <h2 className="font-serif text-[22px] leading-tight text-navy-900 md:text-[24px]">
                    {meta.label}
                  </h2>
                  <span
                    className="inline-flex items-center rounded-full px-2 py-0.5 text-[12px] font-medium"
                    style={{ background: meta.pillBg, color: meta.pillText }}
                  >
                    {g.items.length}
                    {' '}
                    {g.items.length === 1 ? 'Place' : 'Places'}
                  </span>
                </div>
                <p className="mt-1 pl-5 font-serif italic text-[15px] leading-relaxed text-navy-500">
                  {meta.subheading}
                </p>
              </div>

              {hasItems && (
                <span className="shrink-0 pt-1.5 text-navy-500" aria-hidden="true">
                  <svg
                    width="14" height="14" viewBox="0 0 14 14"
                    className={
                      'motion-safe:transition-transform motion-safe:duration-200 ' +
                      (isOpen ? 'rotate-180' : '')
                    }
                  >
                    <path d="M2 5l5 5 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                  </svg>
                </span>
              )}
            </button>

            <div
              id={contentId}
              role="region"
              aria-labelledby={`tier-header-${g.tier}`}
              hidden={!isOpen || !hasItems}
              className="pt-2 pb-2"
            >
              {hasItems && (
                <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
                  {g.items.map((p) => (
                    <PlaceCard key={p.slug} place={p} />
                  ))}
                </div>
              )}
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

function PlaceCard({ place, showTier }: { place: PlaceMock; showTier?: boolean }) {
  const tier       = tierFor(place)
  const meta       = TIER_META[tier]

  // Real curated location artwork always takes precedence over the
  // fallback palette. The fallback only renders when no artwork
  // exists — which is every Place in the current prototype fixture,
  // but the code path is here ready for World-Management-authored
  // images to drop in later. Kept as a background-image on the
  // header div so cover / center behaviour matches the fallback
  // gradient's rendering geometry.
  const artworkUrl = (place as PlaceMock & { hero_artwork_url?: string | null })
    .hero_artwork_url ?? null

  return (
    <article
      aria-labelledby={`place-${place.slug}-name`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white transition-shadow hover:shadow-[0_8px_24px_rgba(12,24,38,0.06)]"
    >
      {artworkUrl ? (
        <div
          aria-hidden="true"
          className="h-28 bg-cover bg-center"
          style={{ backgroundImage: `url("${artworkUrl}")` }}
        />
      ) : (
        <div
          aria-hidden="true"
          className="h-28"
          style={{
            background: atmosphereBackground(
              atmosphereForSlug(place.slug, place.activity === 'emerging'),
            ),
          }}
        />
      )}

      <div className="flex flex-1 flex-col p-5">
        {showTier && (
          <div className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.08em] text-navy-500">
            <span
              aria-hidden="true"
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{ background: meta.dot }}
            />
            <span>
              {tier === 'flourishing' ? 'Flourishing'
                : tier === 'growing'  ? 'Growing'
                :                       'Emerging'}
            </span>
          </div>
        )}

        <h3
          id={`place-${place.slug}-name`}
          className="font-serif text-[20px] leading-tight text-navy-900"
        >
          {place.name}
        </h3>
        <p className="mt-0.5 text-[13px] text-navy-500">
          {place.region}, {place.country}
        </p>

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

        <p className="mt-5 text-[13px] leading-relaxed text-navy-500">
          {characterLineFor(place)}
        </p>
      </div>
    </article>
  )
}
