'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type {
  PhysicalLocationStatus,
  PhysicalLocationSummary,
} from '@/lib/physicalLocations/types'

interface Filters {
  q: string
  status: string
  country: string
  sort: 'alphabetical' | 'recently-updated' | 'most-collectives'
}

interface Props {
  initialLocations: PhysicalLocationSummary[]
  initialFilters: Filters
}

/**
 * Client-side search / filter / sort controls for the Physical
 * Locations list. Server renders the initial catalogue; changes to
 * filters push a fresh URL and let the server round-trip.
 *
 * Kept a client component (rather than pure query-string driven) so
 * search-as-you-type feels responsive and the country dropdown can
 * be derived from the initial payload.
 */
export default function PhysicalLocationsListClient({
  initialLocations,
  initialFilters,
}: Props) {
  const router = useRouter()
  const [filters, setFilters] = useState<Filters>(initialFilters)
  const [locations, setLocations] = useState(initialLocations)
  const [loading, setLoading] = useState(false)

  // Country options are derived from whatever the server returned on
  // first load — a pragmatic middle ground while the catalogue is
  // small. Grows automatically as new countries are added.
  const countryOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const l of initialLocations) seen.add(l.country_code)
    return Array.from(seen).sort()
  }, [initialLocations])

  // Push filter changes as a query string so the URL stays shareable.
  useEffect(() => {
    if (
      filters.q === initialFilters.q
      && filters.status === initialFilters.status
      && filters.country === initialFilters.country
      && filters.sort === initialFilters.sort
    ) {
      return
    }
    const params = new URLSearchParams()
    if (filters.q) params.set('q', filters.q)
    if (filters.status) params.set('status', filters.status)
    if (filters.country) params.set('country', filters.country)
    if (filters.sort !== 'alphabetical') params.set('sort', filters.sort)
    const qs = params.toString()
    router.replace(`/admin/physical-locations${qs ? `?${qs}` : ''}`)
  }, [filters, initialFilters, router])

  // Debounced refetch when filters change — avoids a full server
  // navigation for each keystroke while still respecting the same
  // backend contract.
  useEffect(() => {
    const controller = new AbortController()
    const handle = setTimeout(async () => {
      setLoading(true)
      const params = new URLSearchParams()
      if (filters.q) params.set('q', filters.q)
      if (filters.status) params.set('status', filters.status)
      if (filters.country) params.set('country', filters.country)
      if (filters.sort) params.set('sort', filters.sort)
      try {
        const res = await fetch(
          apiUrl(`/api/admin/physical-locations?${params.toString()}`),
          { credentials: 'include', signal: controller.signal },
        )
        if (res.ok) {
          setLocations(await res.json())
        }
      } catch {
        // Swallow abort noise; anything else is transient.
      } finally {
        setLoading(false)
      }
    }, 220)
    return () => {
      clearTimeout(handle)
      controller.abort()
    }
  }, [filters])

  return (
    <>
      <div
        className="mb-8 rounded-2xl bg-white px-5 py-4 md:px-6"
        style={{
          border: '1px solid rgba(12, 24, 38, 0.06)',
          boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
        }}
      >
        <div className="grid gap-3 md:grid-cols-[1.4fr_1fr_1fr_1.2fr]">
          <input
            type="search"
            value={filters.q}
            onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
            placeholder="Search name or region"
            className="w-full rounded-xl px-4 py-2.5 text-[14px] focus:outline-none"
            style={{
              background: '#FFFFFF',
              border: '1px solid rgba(12, 24, 38, 0.12)',
              color: '#0C1826',
            }}
          />
          <select
            value={filters.status}
            onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
            className="w-full rounded-xl px-4 py-2.5 text-[14px] focus:outline-none"
            style={{
              background: '#FFFFFF',
              border: '1px solid rgba(12, 24, 38, 0.12)',
              color: '#0C1826',
            }}
          >
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="hidden">Hidden</option>
            <option value="archived">Archived</option>
          </select>
          <select
            value={filters.country}
            onChange={(e) => setFilters((f) => ({ ...f, country: e.target.value }))}
            className="w-full rounded-xl px-4 py-2.5 text-[14px] focus:outline-none"
            style={{
              background: '#FFFFFF',
              border: '1px solid rgba(12, 24, 38, 0.12)',
              color: '#0C1826',
            }}
          >
            <option value="">All countries</option>
            {countryOptions.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <select
            value={filters.sort}
            onChange={(e) => setFilters((f) => ({ ...f, sort: e.target.value as Filters['sort'] }))}
            className="w-full rounded-xl px-4 py-2.5 text-[14px] focus:outline-none"
            style={{
              background: '#FFFFFF',
              border: '1px solid rgba(12, 24, 38, 0.12)',
              color: '#0C1826',
            }}
          >
            <option value="alphabetical">Alphabetical</option>
            <option value="recently-updated">Recently updated</option>
            <option value="most-collectives">Most Collectives</option>
          </select>
        </div>
      </div>

      {locations.length === 0 ? (
        <div
          className="rounded-2xl bg-white p-10 text-center"
          style={{ border: '1px dashed rgba(12, 24, 38, 0.15)' }}
        >
          <p className="text-[14px] italic" style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}>
            {loading ? 'Loading…' : 'No Physical Locations match these filters.'}
          </p>
        </div>
      ) : (
        <div
          className="grid gap-6 md:grid-cols-2 lg:grid-cols-3"
          aria-busy={loading}
        >
          {locations.map((loc) => (
            <LocationCard key={loc.id} loc={loc} />
          ))}
        </div>
      )}
    </>
  )
}

function LocationCard({ loc }: { loc: PhysicalLocationSummary }) {
  const artworkUrl = resolveMediaUrl(loc.hero_artwork_url)

  return (
    <Link
      href={`/admin/physical-locations/${loc.slug}`}
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
        {artworkUrl ? (
          <img
            src={artworkUrl}
            alt={loc.artwork_alt_text ?? ''}
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
            style={{
              objectPosition: `${loc.artwork_focal_x * 100}% ${loc.artwork_focal_y * 100}%`,
            }}
          />
        ) : (
          <div
            className="flex h-full w-full items-center justify-center"
            style={{
              background: 'linear-gradient(135deg, rgba(56,160,158,0.12) 0%, rgba(85,184,182,0.05) 100%)',
            }}
          >
            <p
              className="px-4 text-center text-[13px] italic"
              style={{ color: 'rgba(12,24,38,0.42)', fontFamily: 'Georgia, serif' }}
            >
              No artwork yet
            </p>
          </div>
        )}
        <StatusPill status={loc.status} />
      </div>

      <div className="px-6 pt-5 pb-6">
        <h3
          className="font-serif text-[20px] leading-tight"
          style={{ color: '#0C1826' }}
        >
          {loc.name}
        </h3>
        <p
          className="mt-1 text-[12.5px]"
          style={{ color: 'rgba(12, 24, 38, 0.55)' }}
        >
          {[loc.region, loc.country_code].filter(Boolean).join(' · ')}
        </p>
        <p
          className="mt-4 text-[12px]"
          style={{ color: 'rgba(12, 24, 38, 0.50)' }}
        >
          {loc.collective_count === 0
            ? 'No Collectives here yet'
            : loc.collective_count === 1
            ? '1 Collective'
            : `${loc.collective_count} Collectives`}
        </p>
      </div>
    </Link>
  )
}

function StatusPill({ status }: { status: PhysicalLocationStatus }) {
  // 'active' is the default & the largest cohort — don't clutter.
  if (status === 'active') return null

  const palette: Record<Exclude<PhysicalLocationStatus, 'active'>, { bg: string; fg: string; label: string }> = {
    draft:    { bg: 'rgba(212,176,72,0.20)',  fg: '#8B6A1E', label: 'Draft' },
    hidden:   { bg: 'rgba(12,24,38,0.10)',    fg: 'rgba(12,24,38,0.62)', label: 'Hidden' },
    archived: { bg: 'rgba(166,69,38,0.14)',   fg: '#A64526', label: 'Archived' },
  }
  const p = palette[status]
  return (
    <span
      className="absolute right-3 top-3 rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wide"
      style={{
        background: p.bg,
        color: p.fg,
        backdropFilter: 'blur(6px)',
      }}
    >
      {p.label}
    </span>
  )
}
