'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { resolveMediaUrl } from '@/lib/api'
import type {
  AdminCreatorRow,
  AdminCreatorHealth,
  AdminCreatorCollectiveChip,
} from '@/lib/serverApi'
import {
  CSV_MULTI_DELIMITER,
  downloadCsv,
  todayIsoDate,
  type CsvColumn,
} from '@/lib/csvExport'

/**
 * Interactive shell for /admin/creators.
 *
 * Same grammar as CollectivesShell: search + filters + sort + Gallery/List
 * toggle, shared query state, remembered view preference. The card leads
 * with a portrait because a Creator is a person, not a place.
 */

// ---------------------------------------------------------------------------
// Tokens — inherit from Mother World / Collectives.
// ---------------------------------------------------------------------------
const CARD_BG     = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'
const INK         = '#0C1826'
const INK_MUTED   = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER  = 'rgba(12, 24, 38, 0.42)'
const HAIRLINE    = '1px solid rgba(12, 24, 38, 0.06)'

const HUE_HEALTH: Record<AdminCreatorHealth, { dot: string; label: string; chipBg: string; chipBorder: string; chipText: string }> = {
  flourishing:   { dot: '#22a598', label: 'Flourishing',   chipBg: 'rgba(56, 160, 158, 0.10)', chipBorder: 'rgba(56, 160, 158, 0.22)', chipText: '#0f766e' },
  new:           { dot: '#4c78d4', label: 'New',           chipBg: 'rgba(56, 116, 180, 0.10)', chipBorder: 'rgba(56, 116, 180, 0.22)', chipText: '#1e40af' },
  quiet:         { dot: '#d4b048', label: 'Quiet',         chipBg: 'rgba(212, 176, 72, 0.14)', chipBorder: 'rgba(212, 176, 72, 0.30)', chipText: '#8A6A15' },
  needs_support: { dot: '#d66057', label: 'Needs support', chipBg: 'rgba(214, 96, 87, 0.09)',  chipBorder: 'rgba(214, 96, 87, 0.28)',  chipText: '#a63c30' },
}

const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

const VIEW_PREF_KEY = 'fc.admin.creators.view'
type View = 'gallery' | 'list'
type HealthFilter = 'all' | AdminCreatorHealth
type PlanFilter = 'all' | string
type NewFilter = 'all' | 'this_month'
type SortKey = 'recent' | 'newest' | 'members' | 'alpha' | 'needs_care'

// ---------------------------------------------------------------------------

export default function CreatorsShell({ rows }: { rows: AdminCreatorRow[] }) {
  const [view, setView] = useState<View>('gallery')
  const [search, setSearch] = useState('')
  const [health, setHealth] = useState<HealthFilter>('all')
  const [plan, setPlan] = useState<PlanFilter>('all')
  const [newness, setNewness] = useState<NewFilter>('all')
  const [sortKey, setSortKey] = useState<SortKey>('recent')

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

  const planOptions = useMemo(() => {
    const set = new Set<string>()
    for (const r of rows) if (r.plan_name && r.plan_name !== '—') set.add(r.plan_name)
    return Array.from(set).sort()
  }, [rows])

  const filtered = useMemo(() => filterAndSort({
    rows, search, health, plan, newness, sortKey,
  }), [rows, search, health, plan, newness, sortKey])

  const hasFilters =
    search.trim() !== '' ||
    health !== 'all' ||
    plan !== 'all' ||
    newness !== 'all'

  const clearFilters = useCallback(() => {
    setSearch('')
    setHealth('all')
    setPlan('all')
    setNewness('all')
  }, [])

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
      <header className="mb-8">
        <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
          Creators
        </h1>
        <p className="mt-3 max-w-[620px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
          The people bringing Fresh Collective to life.
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
            ['flourishing', 'Flourishing'],
            ['new', 'New'],
            ['quiet', 'Quiet'],
            ['needs_support', 'Needs support'],
          ]}
        />
        <FilterSelect
          label="Plan"
          value={plan}
          onChange={setPlan}
          options={[['all', 'All plans'], ...planOptions.map((p): [string, string] => [p, p])]}
        />
        <FilterSelect
          label="Arrived"
          value={newness}
          onChange={(v) => setNewness(v as NewFilter)}
          options={[
            ['all', 'Any time'],
            ['this_month', 'This month'],
          ]}
        />
        <div className="grow" />
        <FilterSelect
          label="Sort"
          value={sortKey}
          onChange={(v) => setSortKey(v as SortKey)}
          options={[
            ['recent',      'Recently active'],
            ['newest',      'Newly joined'],
            ['members',     'Most members reached'],
            ['alpha',       'Alphabetical'],
            ['needs_care',  'Needs support first'],
          ]}
        />
        <ExportCsvButton
          onExport={() =>
            downloadCsv(
              filtered,
              CREATORS_CSV_COLUMNS,
              `fresh-collective-creators-${todayIsoDate()}.csv`,
            )
          }
          disabled={filtered.length === 0}
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
            <Chip label={healthChipLabel(health)} onClear={() => setHealth('all')} />
          )}
          {plan !== 'all' && (
            <Chip label={`on ${plan}`} onClear={() => setPlan('all')} />
          )}
          {newness === 'this_month' && (
            <Chip label="arrived this month" onClear={() => setNewness('all')} />
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
          filteredCount: filtered.length,
          hasFilters,
          health,
          newness,
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
// Filter + sort
// ---------------------------------------------------------------------------

function filterAndSort(args: {
  rows: AdminCreatorRow[]
  search: string
  health: HealthFilter
  plan: PlanFilter
  newness: NewFilter
  sortKey: SortKey
}): AdminCreatorRow[] {
  const { rows, search, health, plan, newness, sortKey } = args
  const q = search.trim().toLowerCase()
  const monthAgo = Date.now() - 30 * 24 * 60 * 60 * 1000
  const filtered = rows.filter((r) => {
    if (health !== 'all' && r.health !== health) return false
    if (plan !== 'all' && r.plan_name !== plan) return false
    if (newness === 'this_month' && Date.parse(r.created_at) < monthAgo) return false
    if (q) {
      const collectiveNames = r.collectives.map((c) => c.name).join(' ')
      const hay = [r.name ?? '', r.email, collectiveNames].join(' ').toLowerCase()
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
        return b.total_members_reached - a.total_members_reached || (a.name ?? '').localeCompare(b.name ?? '')
      case 'alpha':
        return (a.name ?? a.email).localeCompare(b.name ?? b.email)
      case 'needs_care': {
        const order: Record<AdminCreatorHealth, number> = { needs_support: 0, new: 1, quiet: 2, flourishing: 3 }
        return order[a.health] - order[b.health] || (a.name ?? '').localeCompare(b.name ?? '')
      }
    }
  })
  return arr
}

// ---------------------------------------------------------------------------
// Management strip pieces (mirrors CollectivesShell)
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
        placeholder="Search by name, email or collective…"
        className="w-full rounded-full py-2 pl-9 pr-3 text-[13px] outline-none transition-colors focus:border-teal-300"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
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

function ExportCsvButton({
  onExport, disabled,
}: {
  onExport: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onExport}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-[12.5px] font-medium outline-none transition-colors hover:border-slate-300 disabled:cursor-not-allowed disabled:opacity-50"
      style={{
        background: '#FFFFFF',
        border: '1px solid #E7EEF0',
        color: INK,
      }}
      aria-label="Export the current filtered result set to CSV"
    >
      <svg
        aria-hidden
        width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        style={{ color: INK_SOFTER }}
      >
        <path d="M12 3v12" />
        <path d="m7 10 5 5 5-5" />
        <path d="M5 21h14" />
      </svg>
      Export CSV
    </button>
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

function healthChipLabel(h: AdminCreatorHealth): string {
  switch (h) {
    case 'flourishing':   return 'flourishing'
    case 'new':           return 'newly arrived'
    case 'quiet':         return 'quiet'
    case 'needs_support': return 'may need support'
  }
}

// ---------------------------------------------------------------------------
// Results sentence
// ---------------------------------------------------------------------------

function resultsSentence(args: {
  totalRows: number
  filteredCount: number
  hasFilters: boolean
  health: HealthFilter
  newness: NewFilter
}): string {
  const { totalRows, filteredCount, hasFilters, health, newness } = args
  const n = filteredCount
  if (totalRows === 0) return 'No creators are building here yet.'
  if (n === 0) return 'Nothing in the world matches that yet.'

  if (!hasFilters) {
    if (n === 1) return '1 creator is building the Fresh Collective world.'
    return `${n} creators are building the Fresh Collective world.`
  }
  if (newness === 'this_month') {
    return n === 1 ? '1 creator arrived this month.' : `${n} creators arrived this month.`
  }
  if (health === 'needs_support') {
    return n === 1 ? '1 creator may need some support.' : `${n} creators may need some support.`
  }
  if (health === 'flourishing') {
    return n === 1 ? '1 creator is flourishing.' : `${n} creators are flourishing.`
  }
  if (health === 'quiet') {
    return n === 1 ? '1 creator is quiet across their collectives.' : `${n} creators are quiet across their collectives.`
  }
  if (health === 'new') {
    return n === 1 ? '1 creator is finding their feet.' : `${n} creators are finding their feet.`
  }
  return n === 1 ? '1 creator matches that.' : `${n} creators match that.`
}

// ---------------------------------------------------------------------------
// Gallery view
// ---------------------------------------------------------------------------

function GalleryGrid({ rows }: { rows: AdminCreatorRow[] }) {
  return (
    <div className="grid gap-6 md:gap-7 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((r) => <CreatorCard key={r.id} row={r} />)}
    </div>
  )
}

function CreatorCard({ row }: { row: AdminCreatorRow }) {
  const avatar = resolveMediaUrl(row.avatar_url)
  const healthConfig = HUE_HEALTH[row.health] ?? HUE_HEALTH.new

  return (
    <Link
      href={`/admin/creators/${row.id}`}
      className="group flex flex-col overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <div className="flex items-start gap-4 p-5">
        <AvatarPortrait url={avatar} name={row.name ?? row.email} size={64} />
        <div className="min-w-0 flex-1">
          <h3
            className="font-serif text-[20px] leading-tight md:text-[22px]"
            style={{ color: INK, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {row.name ?? row.email}
          </h3>
          <p className="mt-1 text-[13px]" style={SERIF_ITALIC}>
            Building since {monthYear(row.created_at)}
          </p>
        </div>
      </div>

      {row.collectives.length > 0 && (
        <div className="px-5">
          <CollectiveChips chips={row.collectives} />
        </div>
      )}

      <div className="mt-auto flex items-center justify-between gap-4 px-5 py-4 pt-5">
        <span className="flex items-center gap-2 text-[12.5px]" style={{ color: INK_MUTED }}>
          <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: healthConfig.dot }} aria-hidden />
          <span style={{ color: INK }}>{row.activity_phrase}</span>
        </span>
        <span className="shrink-0 text-[12.5px]" style={{ color: INK_SOFTER }}>
          {membersReachedLabel(row.total_members_reached)}
        </span>
      </div>
    </Link>
  )
}

function CollectiveChips({ chips }: { chips: AdminCreatorCollectiveChip[] }) {
  const visible = chips.slice(0, 3)
  const extra = chips.length - visible.length
  return (
    <div className="flex flex-wrap gap-1.5">
      {visible.map((c) => (
        <span
          key={c.id}
          className="inline-flex max-w-full items-center gap-1 truncate rounded-full px-2.5 py-1 text-[12px]"
          style={{
            background: '#F5F8FA',
            border: '1px solid #E7EEF0',
            color: INK,
          }}
          title={c.name}
        >
          <span aria-hidden>{leadingEmoji(c.location_name) ?? '·'}</span>
          <span className="truncate">{c.name}</span>
        </span>
      ))}
      {extra > 0 && (
        <span
          className="inline-flex items-center rounded-full px-2.5 py-1 text-[12px]"
          style={{ background: '#F5F8FA', border: '1px solid #E7EEF0', color: INK_MUTED }}
        >
          +{extra} more
        </span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// List view
// ---------------------------------------------------------------------------

function ListView({ rows }: { rows: AdminCreatorRow[] }) {
  return (
    <div className="overflow-hidden rounded-2xl" style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}>
      {rows.map((r, i) => <CreatorListRow key={r.id} row={r} first={i === 0} />)}
    </div>
  )
}

function CreatorListRow({ row, first }: { row: AdminCreatorRow; first: boolean }) {
  const avatar = resolveMediaUrl(row.avatar_url)
  const healthConfig = HUE_HEALTH[row.health] ?? HUE_HEALTH.new

  return (
    <Link
      href={`/admin/creators/${row.id}`}
      className="group flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-slate-50/60"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <AvatarPortrait url={avatar} name={row.name ?? row.email} size={40} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-serif text-[16px] leading-tight" style={{ color: INK }}>
            {row.name ?? row.email}
          </span>
          <span className="text-[11.5px]" style={{ color: INK_SOFTER, fontFamily: 'Georgia, serif', fontStyle: 'italic' }}>
            since {monthYear(row.created_at)}
          </span>
        </div>
        {row.collectives.length > 0 && (
          <p className="mt-0.5 truncate text-[11.5px]" style={{ color: INK_SOFTER }}>
            {row.collectives.slice(0, 3).map((c) => c.name).join(' · ')}
            {row.collectives.length > 3 && ` · +${row.collectives.length - 3} more`}
          </p>
        )}
      </div>
      <div className="hidden shrink-0 items-center gap-1.5 text-[12.5px] md:inline-flex" style={{ color: INK_MUTED }}>
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: healthConfig.dot }} aria-hidden />
        {row.activity_phrase}
      </div>
      <div className="shrink-0 tabular-nums text-[13px]" style={{ color: INK, minWidth: 110, textAlign: 'right' }}>
        {membersReachedLabel(row.total_members_reached)}
      </div>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Empty states
// ---------------------------------------------------------------------------

function EmptyWorld() {
  return (
    <div className="rounded-2xl px-10 py-16 text-center" style={{ background: '#FBFDFC', border: CARD_BORDER }}>
      <p className="font-serif text-[22px] leading-tight md:text-[24px]" style={{ color: INK }}>
        No creators are building here yet.
      </p>
      <p className="mx-auto mt-3 max-w-[440px] text-[14px] leading-relaxed" style={SERIF_ITALIC}>
        When someone opens their first collective, they'll appear here.
      </p>
    </div>
  )
}

function EmptyResults({ onClear }: { onClear: () => void }) {
  return (
    <div className="rounded-2xl px-10 py-14 text-center" style={{ background: '#FBFDFC', border: CARD_BORDER }}>
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
// Small pieces
// ---------------------------------------------------------------------------

// Round portrait with a soft two-letter initials fallback. Colour comes
// from a stable hash of the seed so faces don't all look identical when
// avatars are missing.
export function AvatarPortrait({
  url, name, size,
}: { url: string | null; name: string; size: number }) {
  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt=""
        className="shrink-0 rounded-full"
        style={{ width: size, height: size, objectFit: 'cover', border: '1px solid #E7EEF0' }}
      />
    )
  }
  const initials = initialsFor(name)
  const palettes: [string, string][] = [
    ['#E5F0EF', '#0f766e'], // teal
    ['#F1EEE4', '#8A6A15'], // gold
    ['#EEF1F7', '#1e40af'], // blue
    ['#F1EBED', '#a63c30'], // rose
    ['#EDF3ED', '#3f6b3f'], // moss
  ]
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0
  const [bg, fg] = palettes[hash % palettes.length]
  return (
    <div
      className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold"
      style={{
        width: size, height: size,
        background: bg, color: fg,
        border: '1px solid #E7EEF0',
        fontSize: Math.max(11, Math.round(size * 0.36)),
        letterSpacing: '0.02em',
      }}
      aria-hidden
    >
      {initials}
    </div>
  )
}

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0][0]?.toUpperCase() ?? '?'
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function membersReachedLabel(n: number): string {
  if (n === 0) return '0 members reached'
  if (n === 1) return '1 member reached'
  return `${n.toLocaleString('en-AU')} members reached`
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function monthYear(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const name = MONTHS[d.getMonth()]
  const nowYear = new Date().getFullYear()
  return d.getFullYear() === nowYear ? name : `${name} ${d.getFullYear()}`
}

// Locations follow the "emoji + space + name" convention (e.g. "🌿 The
// Grove"). Extract the leading emoji cheaply so we can prefix collective
// chips with their world icon without a separate metadata field.
function leadingEmoji(loc: string | null): string | null {
  if (!loc) return null
  const m = loc.trim().match(/^(\p{Extended_Pictographic}(\uFE0F)?)\s+/u)
  return m ? m[1] : null
}

// ---------------------------------------------------------------------------
// CSV export — same shape as the Members export. Reads from the same
// filtered array the page renders, so search / health / plan / arrived /
// sort all flow through automatically. No internal ids exported.
//
// Roles: mirrors the raw DB role (Creator / Admin). The Members page
// derives multi-badge roles because that surface differentiates owner
// vs. admin; the Creators page displays creators and doesn't render
// role pills, so the CSV mirrors the underlying field for parity.
// ---------------------------------------------------------------------------

const CREATORS_CSV_COLUMNS: CsvColumn<AdminCreatorRow>[] = [
  { header: 'Name',                  value: (r) => r.name ?? '' },
  { header: 'Email',                 value: (r) => r.email },
  { header: 'Roles',                 value: (r) => creatorRoleLabel(r.role) },
  { header: 'Creator since',         value: (r) => monthYear(r.created_at) },
  { header: 'Published collectives', value: (r) => String(r.published_collective_count) },
  { header: 'Draft collectives',     value: (r) => String(r.draft_collective_count) },
  { header: 'Collective names',      value: (r) => r.collectives.map((c) => c.name).join(CSV_MULTI_DELIMITER) },
  { header: 'Members reached',       value: (r) => String(r.total_members_reached) },
  { header: 'Health',                value: (r) => HUE_HEALTH[r.health]?.label ?? '' },
  { header: 'Activity',              value: (r) => r.activity_phrase },
]

function creatorRoleLabel(role: string): string {
  if (!role) return ''
  return role.charAt(0).toUpperCase() + role.slice(1)
}
