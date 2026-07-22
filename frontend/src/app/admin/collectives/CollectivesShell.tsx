'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { resolveMediaUrl } from '@/lib/api'
import type { AdminCollectiveRow, AdminCollectiveHealth } from '@/lib/serverApi'

/**
 * Interactive shell for /admin/collectives.
 *
 * Owns the shared query state (search, three filters, sort, view). Gallery
 * and List consume the same filtered list, so switching views never loses
 * context. View preference is persisted per browser.
 */

// ---------------------------------------------------------------------------
// Design tokens — inherit from Mother World / Atlas so the surface feels
// like part of the same family without importing a shared module.
// ---------------------------------------------------------------------------
const CARD_BG     = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'
const INK         = '#0C1826'
const INK_MUTED   = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER  = 'rgba(12, 24, 38, 0.42)'
const HAIRLINE    = '1px solid rgba(12, 24, 38, 0.06)'

const HUE_HEALTH: Record<AdminCollectiveHealth, { dot: string; label: string }> = {
  healthy:         { dot: '#22a598', label: 'Healthy' },
  quiet:           { dot: '#d4b048', label: 'Quiet' },
  needs_attention: { dot: '#d66057', label: 'Needs attention' },
}

const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

const VIEW_PREF_KEY = 'fc.admin.collectives.view'
type View = 'gallery' | 'list'
type HealthFilter = 'all' | AdminCollectiveHealth
type SortKey = 'recent' | 'newest' | 'members' | 'alpha'
// Status filter is intentionally not exposed: World Management only shows
// live (active) collectives, so the filter would have a single meaningful
// option. Drafts live in the creator studio; archived collectives are
// filtered out at the backend and not surfaced here yet.

// ---------------------------------------------------------------------------

export default function CollectivesShell({ rows }: { rows: AdminCollectiveRow[] }) {
  const [view, setView] = useState<View>('gallery')
  const [search, setSearch] = useState('')
  const [health, setHealth] = useState<HealthFilter>('all')
  const [locationId, setLocationId] = useState<string>('all')
  const [creatorId, setCreatorId] = useState<string>('all')
  const [sortKey, setSortKey] = useState<SortKey>('recent')

  // Restore the caretaker's view preference on mount. Writing happens in
  // the toggle handler itself (see `chooseView` below) rather than an
  // effect so React StrictMode's double-invoked mount can't clobber the
  // stored value with the initial default.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(VIEW_PREF_KEY)
      if (stored === 'gallery' || stored === 'list') setView(stored)
    } catch { /* ignore */ }
  }, [])
  const chooseView = useCallback((v: View) => {
    setView(v)
    try { window.localStorage.setItem(VIEW_PREF_KEY, v) } catch { /* ignore */ }
  }, [])

  // Distinct locations + creators derived from the current rows — no separate
  // fetch, no stale dropdown values.
  const locationOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const r of rows) if (r.location_id && r.location_name) map.set(r.location_id, r.location_name)
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]))
  }, [rows])
  const creatorOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const r of rows) if (r.creator_id) map.set(r.creator_id, r.creator_name ?? r.creator_email ?? '—')
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]))
  }, [rows])

  const filtered = useMemo(() => filterAndSort({
    rows, search, health, locationId, creatorId, sortKey,
  }), [rows, search, health, locationId, creatorId, sortKey])

  const hasFilters =
    search.trim() !== '' ||
    health !== 'all' ||
    locationId !== 'all' ||
    creatorId !== 'all'

  const clearFilters = useCallback(() => {
    setSearch('')
    setHealth('all')
    setLocationId('all')
    setCreatorId('all')
  }, [])

  const activeLocationName = locationOptions.find(([id]) => id === locationId)?.[1]
  const activeCreatorName = creatorOptions.find(([id]) => id === creatorId)?.[1]

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
      {/* Header */}
      <header className="mb-8">
        <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
          Collectives
        </h1>
        <p className="mt-3 max-w-[620px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
          The communities alive in Fresh Collective right now.
        </p>
      </header>

      {/* Management strip */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SearchInput value={search} onChange={setSearch} />
        <FilterSelect
          label="Health"
          value={health}
          onChange={(v) => setHealth(v as HealthFilter)}
          options={[
            ['all', 'All health'],
            ['healthy', 'Healthy'],
            ['quiet', 'Quiet'],
            ['needs_attention', 'Needs attention'],
          ]}
        />
        <FilterSelect
          label="Location"
          value={locationId}
          onChange={setLocationId}
          options={[['all', 'All locations'], ...locationOptions.map(([id, name]): [string, string] => [id, name])]}
        />
        <FilterSelect
          label="Creator"
          value={creatorId}
          onChange={setCreatorId}
          options={[['all', 'All creators'], ...creatorOptions.map(([id, name]): [string, string] => [id, name])]}
        />
        <div className="grow" />
        <FilterSelect
          label="Sort"
          value={sortKey}
          onChange={(v) => setSortKey(v as SortKey)}
          options={[
            ['recent',  'Recently active'],
            ['newest',  'Newly opened'],
            ['members', 'Most members'],
            ['alpha',   'Alphabetical'],
          ]}
        />
        <ViewToggle view={view} onChange={chooseView} />
      </div>

      {/* Active filter chips */}
      {hasFilters && (
        <div className="mb-5 flex flex-wrap items-center gap-2">
          {search.trim() && (
            <Chip label={`matching "${search.trim()}"`} onClear={() => setSearch('')} />
          )}
          {health !== 'all' && (
            <Chip label={health === 'needs_attention' ? 'needs attention' : health} onClear={() => setHealth('all')} />
          )}
          {locationId !== 'all' && activeLocationName && (
            <Chip label={`in ${activeLocationName}`} onClear={() => setLocationId('all')} />
          )}
          {creatorId !== 'all' && activeCreatorName && (
            <Chip label={`created by ${firstName(activeCreatorName)}`} onClear={() => setCreatorId('all')} />
          )}
          <button
            type="button"
            onClick={clearFilters}
            className="ml-1 text-[12.5px] font-semibold transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
          >
            Clear all
          </button>
        </div>
      )}

      {/* Results sentence */}
      <p className="mb-6 text-[13.5px]" style={SERIF_ITALIC}>
        {resultsSentence({
          totalRows: rows.length,
          filteredRows: filtered,
          hasFilters,
          health,
          locationName: activeLocationName ?? null,
        })}
      </p>

      {/* Body */}
      {rows.length === 0 ? (
        <EmptyWorld />
      ) : filtered.length === 0 ? (
        <EmptyResults onClear={clearFilters} />
      ) : view === 'gallery' ? (
        <GalleryGrid rows={filtered} />
      ) : (
        <ListView rows={filtered} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filtering + sorting
// ---------------------------------------------------------------------------

function filterAndSort(args: {
  rows: AdminCollectiveRow[]
  search: string
  health: HealthFilter
  locationId: string
  creatorId: string
  sortKey: SortKey
}): AdminCollectiveRow[] {
  const { rows, search, health, locationId, creatorId, sortKey } = args
  const q = search.trim().toLowerCase()
  const filtered = rows.filter((r) => {
    if (health !== 'all' && r.health !== health) return false
    if (locationId !== 'all' && r.location_id !== locationId) return false
    if (creatorId !== 'all' && r.creator_id !== creatorId) return false
    if (q) {
      const hay = [
        r.name,
        r.creator_name ?? '',
        r.creator_email ?? '',
        r.location_name ?? '',
      ].join(' ').toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
  const arr = [...filtered]
  arr.sort((a, b) => {
    switch (sortKey) {
      case 'recent': {
        const av = a.last_activity_at ? Date.parse(a.last_activity_at) : Date.parse(a.created_at)
        const bv = b.last_activity_at ? Date.parse(b.last_activity_at) : Date.parse(b.created_at)
        return bv - av
      }
      case 'newest':
        return Date.parse(b.created_at) - Date.parse(a.created_at)
      case 'members':
        return b.member_count - a.member_count || a.name.localeCompare(b.name)
      case 'alpha':
        return a.name.localeCompare(b.name)
    }
  })
  return arr
}

// ---------------------------------------------------------------------------
// Management strip pieces
// ---------------------------------------------------------------------------

function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative min-w-[220px] flex-1 basis-[240px]">
      <svg
        aria-hidden
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2"
        width="14" height="14" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        style={{ color: INK_SOFTER }}
      >
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search collectives, creators or locations…"
        className="w-full rounded-full py-2 pl-9 pr-3 text-[13px] outline-none transition-colors focus:border-teal-300"
        style={{
          background: '#FFFFFF',
          border: '1px solid #E7EEF0',
          color: INK,
        }}
      />
    </div>
  )
}

function FilterSelect({
  label, value, onChange, options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: [string, string][]
}) {
  return (
    <label className="relative inline-flex items-center">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="cursor-pointer appearance-none rounded-full py-2 pl-3 pr-8 text-[12.5px] font-medium outline-none transition-colors hover:border-slate-300"
        style={{
          background: '#FFFFFF',
          border: '1px solid #E7EEF0',
          color: value === 'all' ? INK_MUTED : INK,
        }}
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>{v === 'all' ? l : `${label}: ${l}`}</option>
        ))}
      </select>
      <svg
        aria-hidden
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2"
        width="10" height="10" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        style={{ color: INK_SOFTER }}
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </label>
  )
}

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const btn = (v: View, label: string, icon: React.ReactNode) => {
    const active = view === v
    return (
      <button
        type="button"
        onClick={() => onChange(v)}
        aria-pressed={active}
        className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-semibold transition-colors"
        style={{
          background: active ? '#EEF7F6' : 'transparent',
          color: active ? '#0f766e' : INK_MUTED,
        }}
      >
        {icon}
        {label}
      </button>
    )
  }
  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-full p-0.5"
      style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
    >
      {btn('gallery', 'Gallery', (
        <svg aria-hidden width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
        </svg>
      ))}
      {btn('list', 'List', (
        <svg aria-hidden width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      ))}
    </div>
  )
}

function Chip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full py-1 pl-3 pr-1 text-[12px]"
      style={{ background: '#EEF7F6', border: '1px solid rgba(56,160,158,0.22)', color: '#0f766e' }}
    >
      {label}
      <button
        type="button"
        onClick={onClear}
        aria-label={`Remove filter: ${label}`}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full transition-colors hover:bg-white/60"
      >
        <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </span>
  )
}

// ---------------------------------------------------------------------------
// Results sentence
// ---------------------------------------------------------------------------

function resultsSentence(args: {
  totalRows: number
  filteredRows: AdminCollectiveRow[]
  hasFilters: boolean
  health: HealthFilter
  locationName: string | null
}): string {
  const { filteredRows, hasFilters, health, locationName, totalRows } = args
  const n = filteredRows.length
  if (totalRows === 0) return 'No collectives are living in the world yet.'
  if (n === 0) return 'Nothing in the world matches that yet.'

  const noun = n === 1 ? 'collective' : 'collectives'
  if (!hasFilters) {
    return `${n} ${noun} ${n === 1 ? 'calls' : 'call'} Fresh Collective home.`
  }
  if (locationName) {
    return `${n} ${noun} ${n === 1 ? 'lives' : 'live'} in ${locationName}.`
  }
  if (health === 'needs_attention') {
    return `${n} ${noun} ${n === 1 ? 'needs' : 'need'} your attention.`
  }
  if (health === 'quiet') {
    return n === 1 ? '1 collective is quiet this month.' : `${n} collectives are quiet this month.`
  }
  return `${n} ${noun} ${n === 1 ? 'matches' : 'match'} that.`
}

// ---------------------------------------------------------------------------
// Gallery view
// ---------------------------------------------------------------------------

function GalleryGrid({ rows }: { rows: AdminCollectiveRow[] }) {
  return (
    <div className="grid gap-6 md:gap-7 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((r) => (
        <CollectiveCard key={r.id} row={r} />
      ))}
    </div>
  )
}

function CollectiveCard({ row }: { row: AdminCollectiveRow }) {
  const cover = collectiveImage(row)
  const healthConfig = HUE_HEALTH[row.health] ?? HUE_HEALTH.healthy

  return (
    <Link
      href={`/admin/collectives/${row.slug}`}
      className="group block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      {/* Cover — 5:3 landscape */}
      <div className="relative w-full overflow-hidden" style={{ aspectRatio: '5 / 3' }}>
        {cover ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={cover}
            alt=""
            className="absolute inset-0 h-full w-full"
            style={{ objectFit: 'cover' }}
          />
        ) : (
          <CoverPlaceholder seed={row.slug} />
        )}
      </div>

      {/* Body */}
      <div className="p-5">
        {row.location_name && (
          <span
            className="mb-1.5 inline-flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: INK_SOFTER }}
          >
            <PinIcon />
            {row.location_name}
          </span>
        )}
        <h3
          className="font-serif text-[20px] leading-tight md:text-[22px]"
          style={{ color: INK, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {row.name}
        </h3>
        {row.creator_name && (
          <p className="mt-1 text-[13px]" style={SERIF_ITALIC}>
            by {row.creator_name}
          </p>
        )}

        {/* Pulse line */}
        <div className="mt-4 flex items-center gap-2 text-[12.5px]" style={{ color: INK_MUTED }}>
          <span
            className="inline-block h-2 w-2 shrink-0 rounded-full"
            style={{ background: healthConfig.dot }}
            aria-hidden
          />
          <span>{memberLabel(row.member_count)}</span>
          <span aria-hidden style={{ color: INK_SOFTER }}>·</span>
          <span style={{ color: INK }}>{row.activity_phrase}</span>
        </div>
      </div>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// List view — same six facts, one row per collective
// ---------------------------------------------------------------------------

function ListView({ rows }: { rows: AdminCollectiveRow[] }) {
  return (
    <div className="overflow-hidden rounded-2xl" style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}>
      {rows.map((r, i) => (
        <CollectiveListRow key={r.id} row={r} first={i === 0} />
      ))}
    </div>
  )
}

function CollectiveListRow({
  row, first,
}: { row: AdminCollectiveRow; first: boolean }) {
  const cover = collectiveImage(row)
  const healthConfig = HUE_HEALTH[row.health] ?? HUE_HEALTH.healthy

  return (
    <Link
      href={`/admin/collectives/${row.slug}`}
      className="group flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-slate-50/60"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <div
        className="relative shrink-0 overflow-hidden rounded-lg"
        style={{ width: 56, height: 40 }}
      >
        {cover ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={cover}
            alt=""
            className="h-full w-full"
            style={{ objectFit: 'cover' }}
          />
        ) : (
          <CoverPlaceholder seed={row.slug} tiny />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-serif text-[16px] leading-tight" style={{ color: INK }}>
            {row.name}
          </span>
        </div>
        {(row.creator_name || row.location_name) && (
          <div className="mt-0.5 flex items-center gap-2 text-[12px]" style={{ color: INK_SOFTER }}>
            {row.creator_name && (
              <span style={{ fontFamily: 'Georgia, serif', fontStyle: 'italic' }}>by {row.creator_name}</span>
            )}
            {row.creator_name && row.location_name && <span aria-hidden>·</span>}
            {row.location_name && (
              <span
                className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.14em]"
                style={{ color: INK_SOFTER }}
              >
                <PinIcon />
                {row.location_name}
              </span>
            )}
          </div>
        )}
      </div>

      <div
        className="hidden shrink-0 items-center gap-1.5 text-[12.5px] md:inline-flex"
        style={{ color: INK_MUTED }}
      >
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ background: healthConfig.dot }}
          aria-hidden
        />
        {row.activity_phrase}
      </div>

      <div className="shrink-0 tabular-nums text-[13px]" style={{ color: INK, minWidth: 80, textAlign: 'right' }}>
        {memberLabel(row.member_count)}
      </div>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Empty states
// ---------------------------------------------------------------------------

function EmptyWorld() {
  return (
    <div
      className="rounded-2xl px-10 py-16 text-center"
      style={{ background: '#FBFDFC', border: CARD_BORDER }}
    >
      <p className="font-serif text-[22px] leading-tight md:text-[24px]" style={{ color: INK }}>
        No collectives are living in the world yet.
      </p>
      <p className="mx-auto mt-3 max-w-[440px] text-[14px] leading-relaxed" style={SERIF_ITALIC}>
        Published collectives will appear here once creators open them to members.
      </p>
    </div>
  )
}

function EmptyResults({ onClear }: { onClear: () => void }) {
  return (
    <div
      className="rounded-2xl px-10 py-14 text-center"
      style={{ background: '#FBFDFC', border: CARD_BORDER }}
    >
      <p className="font-serif text-[20px] leading-tight" style={{ color: INK }}>
        Nothing in the world matches that yet.
      </p>
      <button
        type="button"
        onClick={onClear}
        className="mt-4 rounded-full px-4 py-2 text-[12.5px] font-semibold transition-colors hover:bg-white"
        style={{ border: '1px solid #E7EEF0', color: INK }}
      >
        Clear filters
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

// Image priority in World Management: the collective's Atlas Location
// hero artwork (chosen inside Build Your Collective and rendered on the
// member-facing collective page). Falls back to the legacy banner, then
// to the deterministic topographic placeholder for collectives with
// neither. Deliberately does not read `Space.island_artwork_url`, which
// is a stale unused column.
function collectiveImage(row: AdminCollectiveRow): string | null {
  return resolveMediaUrl(row.location_hero_artwork_url ?? row.cover_image_url)
}

function memberLabel(n: number): string {
  if (n === 0) return '0 members'
  if (n === 1) return '1 member'
  return `${n.toLocaleString('en-AU')} members`
}

function firstName(full: string): string {
  return full.split(/\s+/)[0] || full
}

function PinIcon() {
  return (
    <svg width="9" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 22s7-6.5 7-12a7 7 0 1 0-14 0c0 5.5 7 12 7 12z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  )
}

// A soft topographic placeholder, matching the World Artwork empty state.
// A stable hash on the seed picks one of a small palette so the card grid
// doesn't feel identical when many collectives lack cover art.
function CoverPlaceholder({
  seed, tiny,
}: { seed: string; tiny?: boolean }) {
  const palettes: [string, string, string][] = [
    ['#E5F0EF', '#F4F7F6', '#FBFDFC'], // teal-mist
    ['#F1EEE4', '#F7F4EA', '#FBF9F1'], // parchment
    ['#EEF1F7', '#F5F7FB', '#FBFCFE'], // blue-mist
    ['#F1EBED', '#F7F1F3', '#FBF6F7'], // rose-mist
  ]
  let hash = 0
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  const [c0, c1, c2] = palettes[hash % palettes.length]
  const gradId = `pc-${seed.replace(/[^\w-]/g, '_')}`
  return (
    <svg
      viewBox="0 0 400 240"
      preserveAspectRatio="xMidYMid slice"
      className="h-full w-full"
      aria-hidden
    >
      <defs>
        <radialGradient id={gradId} cx="0.5" cy="0.55" r="0.75">
          <stop offset="0%" stopColor={c0} />
          <stop offset="60%" stopColor={c1} />
          <stop offset="100%" stopColor={c2} />
        </radialGradient>
      </defs>
      <rect width="400" height="240" fill={`url(#${gradId})`} />
      {!tiny && (
        <g fill="none" stroke="rgba(56, 160, 158, 0.16)" strokeWidth="0.9">
          <ellipse cx="200" cy="130" rx="140" ry="60" />
          <ellipse cx="200" cy="130" rx="95"  ry="42" />
          <ellipse cx="200" cy="130" rx="55"  ry="26" />
        </g>
      )}
    </svg>
  )
}
