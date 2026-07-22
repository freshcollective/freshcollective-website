'use client'

import { useEffect, useMemo, useState } from 'react'
import { apiUrl } from '@/lib/api'
import {
  CSV_MULTI_DELIMITER,
  downloadCsv,
  todayIsoDate,
  type CsvColumn,
} from '@/lib/csvExport'

interface CollectiveRef {
  id: string
  name: string
  slug: string
}

interface MemberRow {
  id: string
  name: string | null
  email: string
  // Derived, human-facing role badges: any subset of
  // ['owner', 'admin', 'creator', 'member'], ordered by the backend from
  // most privileged to least. Rendered as one pill each.
  roles: string[]
  created_at: string
  joined_collectives: CollectiveRef[]
  owned_collectives: CollectiveRef[]
}

// ---------------------------------------------------------------------------
// Design tokens — inherit from Mother World / Collectives / Creators so this
// surface feels like part of the same family without importing a shared
// module.
// ---------------------------------------------------------------------------
const PAGE_BG      = '#FBFDFC'   // soft off-white — the wash used in WM empty states
// Controls panel uses Mother World's HUE.blue palette — a canonical
// pale blue-grey, deep enough to read as a deliberate section without
// clashing with the teal chips it contains.
const PANEL_BG     = 'rgba(56, 116, 180, 0.10)'
const PANEL_BORDER = '1px solid rgba(56, 116, 180, 0.22)'
const CARD_BG     = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'
const INK         = '#0C1826'
const INK_MUTED   = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER  = 'rgba(12, 24, 38, 0.42)'
const HAIRLINE    = '1px solid rgba(12, 24, 38, 0.06)'

const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

type RoleFilter = 'all' | 'owner' | 'admin' | 'creator' | 'member'
type SortKey = 'recent' | 'alpha' | 'belonging'

// Each role gets its own Mother World HUE so the pills carry a little
// warmth without becoming saturated badges. Any future / unknown role
// falls through to the coral system palette rather than silently
// inheriting Member blue.
//
// Owner is the platform founder (only one — see PLATFORM_OWNER_EMAIL on
// the backend). Admin is reserved for future platform staff who aren't
// the owner. Creator = owns at least one collective. Member = has at
// least one active membership.
const HUE_ROLE: Record<string, { chipBg: string; chipBorder: string; chipText: string; label: string }> = {
  owner:   { chipBg: '#F7F1E4', chipBorder: 'rgba(212, 176, 72, 0.32)', chipText: '#8a6a17', label: 'Owner' },
  admin:   { chipBg: '#FBEFEC', chipBorder: 'rgba(214, 96, 87, 0.30)',  chipText: '#a63c30', label: 'Admin' },
  creator: { chipBg: '#EEF7F6', chipBorder: 'rgba(56, 160, 158, 0.30)', chipText: '#0f766e', label: 'Creator' },
  member:  { chipBg: '#EEF3F9', chipBorder: 'rgba(56, 116, 180, 0.30)', chipText: '#1e40af', label: 'Member' },
}
// All four Mother World hues (gold, coral, green, blue) are claimed
// above. A genuinely unknown role falls back to a neutral ink chip so
// it's obviously "unclassified" rather than masquerading as one of the
// canonical badges.
const HUE_ROLE_SYSTEM = {
  chipBg: '#F1F3F5',
  chipBorder: 'rgba(12, 24, 38, 0.14)',
  chipText: INK_MUTED,
}

// ---------------------------------------------------------------------------

export default function MembersPage() {
  const [rows, setRows] = useState<MemberRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [role, setRole] = useState<RoleFilter>('all')
  const [sortKey, setSortKey] = useState<SortKey>('recent')

  useEffect(() => {
    fetch(apiUrl('/api/admin/platform/users'), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json()
      })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(
    () => filterAndSort({ rows, search, role, sortKey }),
    [rows, search, role, sortKey],
  )

  const hasFilters = search.trim() !== '' || role !== 'all'

  const clearFilters = () => {
    setSearch('')
    setRole('all')
  }

  return (
    <div style={{ background: PAGE_BG, minHeight: '100%' }}>
      <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
        {/* Header */}
        <header className="mb-8">
          <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
            Members
          </h1>
          <p className="mt-3 max-w-[620px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
            Everyone who belongs somewhere in our world.
          </p>
        </header>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState message={error} />
        ) : rows.length === 0 ? (
          <EmptyWorld />
        ) : (
          <>
            {/* Grouped controls panel — subtle wash so the controls read as
                one layer between page and table. */}
            <div
              className="mb-6 rounded-2xl p-2.5"
              style={{ background: PANEL_BG, border: PANEL_BORDER }}
            >
              <div className="flex flex-wrap items-center gap-2">
                <SearchInput value={search} onChange={setSearch} />
                <FilterSelect
                  label="Role"
                  value={role}
                  onChange={(v) => setRole(v as RoleFilter)}
                  options={[
                    ['all',     'All roles'],
                    ['member',  'Members'],
                    ['creator', 'Creators'],
                    ['admin',   'Admins'],
                    ['owner',   'Owners'],
                  ]}
                />
                <div className="grow" />
                <FilterSelect
                  label="Sort"
                  value={sortKey}
                  onChange={(v) => setSortKey(v as SortKey)}
                  options={[
                    ['recent',    'Recently arrived'],
                    ['alpha',     'Alphabetical'],
                    ['belonging', 'Most belonging'],
                  ]}
                />
                <ExportCsvButton
                  onExport={() =>
                    downloadCsv(
                      filtered,
                      MEMBERS_CSV_COLUMNS,
                      `fresh-collective-members-${todayIsoDate()}.csv`,
                    )
                  }
                  disabled={filtered.length === 0}
                />
              </div>

              {/* Active filter chips */}
              {hasFilters && (
                <div className="mt-2.5 flex flex-wrap items-center gap-2 px-1">
                  {search.trim() && (
                    <Chip label={`matching "${search.trim()}"`} onClear={() => setSearch('')} />
                  )}
                  {role !== 'all' && (
                    <Chip label={roleFilterLabel(role)} onClear={() => setRole('all')} />
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
            </div>

            {/* Results sentence */}
            <p className="mb-6 text-[13.5px]" style={SERIF_ITALIC}>
              {resultsSentence({
                totalRows: rows.length,
                filteredCount: filtered.length,
                hasFilters,
                role,
                search: search.trim(),
              })}
            </p>

            {/* Body */}
            {filtered.length === 0 ? (
              <EmptyResults onClear={clearFilters} />
            ) : (
              <MembersTable rows={filtered} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filtering + sorting
// ---------------------------------------------------------------------------

function filterAndSort(args: {
  rows: MemberRow[]
  search: string
  role: RoleFilter
  sortKey: SortKey
}): MemberRow[] {
  const { rows, search, role, sortKey } = args
  const q = search.trim().toLowerCase()
  const filtered = rows.filter((r) => {
    if (role !== 'all' && !r.roles.includes(role)) return false
    if (q) {
      const hay = [r.name ?? '', r.email].join(' ').toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
  const arr = [...filtered]
  arr.sort((a, b) => {
    switch (sortKey) {
      case 'recent':
        return Date.parse(b.created_at) - Date.parse(a.created_at)
      case 'alpha': {
        const an = (a.name ?? a.email).toLowerCase()
        const bn = (b.name ?? b.email).toLowerCase()
        return an.localeCompare(bn)
      }
      case 'belonging': {
        // Sort by the *union* size — the same "Belongs to" the row shows.
        // Owned collectives count once, not twice, even if the user is
        // also a learner-member of their own collective.
        const av = belongsTo(a).length
        const bv = belongsTo(b).length
        return bv - av || (a.name ?? a.email).localeCompare(b.name ?? b.email)
      }
    }
  })
  return arr
}

// ---------------------------------------------------------------------------
// "Belongs to" aggregation — union of learner memberships + owned collectives,
// deduped by collective id. Display-and-export rule only; the underlying
// membership model is untouched. A creator's own collectives appear in both
// "Belongs to" and "Creator of" because in practice they belong to what they
// have made — but we never invent a learner-membership row for them.
// ---------------------------------------------------------------------------
function belongsTo(row: MemberRow): CollectiveRef[] {
  const seen = new Set<string>()
  const out: CollectiveRef[] = []
  for (const c of [...row.joined_collectives, ...row.owned_collectives]) {
    if (seen.has(c.id)) continue
    seen.add(c.id)
    out.push(c)
  }
  out.sort((a, b) => a.name.localeCompare(b.name))
  return out
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
        placeholder="Search by name or email…"
        className="w-full rounded-full py-2 pl-9 pr-3 text-[13px] outline-none transition-colors focus:border-teal-300"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
      />
    </div>
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
  filteredCount: number
  hasFilters: boolean
  role: RoleFilter
  search: string
}): string {
  const { filteredCount: n, hasFilters, role, search, totalRows } = args
  if (totalRows === 0) return 'No members have arrived yet.'
  if (n === 0) return 'No members match that search yet.'

  if (!hasFilters) {
    return n === 1
      ? '1 member belongs across the Fresh Collective world.'
      : `${n} members belong across the Fresh Collective world.`
  }
  if (search) {
    return n === 1
      ? `1 member matches "${search}".`
      : `${n} members match "${search}".`
  }
  if (role === 'creator') {
    return n === 1
      ? '1 creator is tending a collective here.'
      : `${n} creators are tending collectives here.`
  }
  if (role === 'admin') {
    return n === 1
      ? '1 admin helps hold this world.'
      : `${n} admins help hold this world.`
  }
  if (role === 'owner') {
    return n === 1
      ? '1 owner holds this world.'
      : `${n} owners hold this world.`
  }
  return n === 1
    ? '1 member belongs across the Fresh Collective world.'
    : `${n} members belong across the Fresh Collective world.`
}

function roleFilterLabel(role: RoleFilter): string {
  switch (role) {
    case 'member':  return 'members'
    case 'creator': return 'creators'
    case 'admin':   return 'admins'
    case 'owner':   return 'owners'
    default:        return ''
  }
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

function MembersTable({ rows }: { rows: MemberRow[] }) {
  return (
    <div
      className="overflow-hidden rounded-2xl"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      {/* Desktop table */}
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full text-left">
          <thead>
            <tr>
              {['Member', 'Roles', 'Belongs to', 'Creator of', 'Joined FC on'].map((h) => (
                <th
                  key={h}
                  className="px-6 py-3.5 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
                  style={{ color: INK_SOFTER, borderBottom: HAIRLINE }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <MemberDesktopRow key={row.id} row={row} first={i === 0} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="lg:hidden">
        {rows.map((row, i) => (
          <MemberMobileRow key={row.id} row={row} first={i === 0} />
        ))}
      </div>
    </div>
  )
}

function MemberDesktopRow({ row, first }: { row: MemberRow; first: boolean }) {
  return (
    <tr
      className="transition-colors hover:bg-slate-50/60"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <td className="px-6 py-4 align-top">
        <div className="font-serif text-[15px] leading-tight" style={{ color: INK }}>
          {row.name ?? '—'}
        </div>
        <div className="mt-1 text-[12.5px]" style={{ color: INK_MUTED }}>
          {row.email}
        </div>
      </td>
      <td className="px-6 py-4 align-top">
        <RoleChips roles={row.roles} />
      </td>
      <td className="px-6 py-4 align-top">
        <CollectivesList items={belongsTo(row)} />
      </td>
      <td className="px-6 py-4 align-top">
        <CollectivesList items={row.owned_collectives} />
      </td>
      <td className="px-6 py-4 align-top text-[13px]" style={{ color: INK_MUTED }}>
        {sinceLabel(row.created_at)}
      </td>
    </tr>
  )
}

function MemberMobileRow({ row, first }: { row: MemberRow; first: boolean }) {
  return (
    <div
      className="px-5 py-4"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-serif text-[15px] leading-tight" style={{ color: INK }}>
            {row.name ?? '—'}
          </div>
          <div className="mt-1 truncate text-[12.5px]" style={{ color: INK_MUTED }}>
            {row.email}
          </div>
        </div>
        <RoleChips roles={row.roles} />
      </div>
      {belongsTo(row).length > 0 && (
        <MobileCollectivesLine label="Belongs to" items={belongsTo(row)} />
      )}
      {row.owned_collectives.length > 0 && (
        <MobileCollectivesLine label="Creator of" items={row.owned_collectives} />
      )}
      <div className="mt-2 text-[12px]" style={{ color: INK_MUTED }}>
        Joined FC on {sinceLabel(row.created_at)}
      </div>
    </div>
  )
}

function RoleChips({ roles }: { roles: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {roles.map((r) => (
        <RoleChip key={r} role={r} />
      ))}
    </div>
  )
}

function RoleChip({ role }: { role: string }) {
  const config = resolveRoleConfig(role)
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold"
      style={{ background: config.chipBg, border: `1px solid ${config.chipBorder}`, color: config.chipText }}
    >
      {config.label}
    </span>
  )
}

// Unknown roles get a neutral ink chip + title-cased label, so any
// role the frontend doesn't recognise reads as "unclassified" rather
// than silently masquerading as one of the canonical badges.
function resolveRoleConfig(role: string) {
  const known = HUE_ROLE[role]
  if (known) return known
  return {
    ...HUE_ROLE_SYSTEM,
    label: role ? role.charAt(0).toUpperCase() + role.slice(1) : 'Role',
  }
}

// ---------------------------------------------------------------------------
// Collective lists — the actual names a person belongs to / has created.
// Names are far more useful than counts. First three shown, then "+N more"
// so a Creator of ten collectives doesn't blow out the row height.
// ---------------------------------------------------------------------------

const COLLECTIVES_VISIBLE = 3

function CollectivesList({ items }: { items: CollectiveRef[] }) {
  if (items.length === 0) {
    return <span className="text-[13px]" style={{ color: INK_SOFTER }}>—</span>
  }
  const visible = items.slice(0, COLLECTIVES_VISIBLE)
  const overflow = items.length - visible.length
  return (
    <div className="flex flex-col gap-0.5">
      {visible.map((c) => (
        <span
          key={c.id}
          className="text-[13px] leading-snug"
          style={{ color: INK }}
        >
          {c.name}
        </span>
      ))}
      {overflow > 0 && (
        <span className="mt-0.5 text-[12px]" style={{ color: INK_MUTED }}>
          +{overflow} more
        </span>
      )}
    </div>
  )
}

function MobileCollectivesLine({ label, items }: { label: string; items: CollectiveRef[] }) {
  const visible = items.slice(0, COLLECTIVES_VISIBLE)
  const overflow = items.length - visible.length
  const names = visible.map((c) => c.name).join(', ')
  return (
    <div className="mt-2 text-[12.5px]" style={{ color: INK_MUTED }}>
      <span style={{ color: INK_SOFTER }}>{label}: </span>
      <span style={{ color: INK }}>{names}</span>
      {overflow > 0 && <span> +{overflow} more</span>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CSV export — columns are derived from the same filtered array the table
// renders, so search / role filter / sort are reflected in the download.
// No internal ids; timestamps normalised to the day.
// ---------------------------------------------------------------------------

const MEMBERS_CSV_COLUMNS: CsvColumn<MemberRow>[] = [
  { header: 'Name',                     value: (r) => r.name ?? '' },
  { header: 'Email',                    value: (r) => r.email },
  { header: 'Roles',                    value: (r) => r.roles.map(roleCsvLabel).join(CSV_MULTI_DELIMITER) },
  { header: 'Belongs to',               value: (r) => belongsTo(r).map((c) => c.name).join(CSV_MULTI_DELIMITER) },
  { header: 'Creator of',               value: (r) => r.owned_collectives.map((c) => c.name).join(CSV_MULTI_DELIMITER) },
  { header: 'Joined Fresh Collective on', value: (r) => csvDateLabel(r.created_at) },
]

function roleCsvLabel(role: string): string {
  return HUE_ROLE[role]?.label ?? (role ? role.charAt(0).toUpperCase() + role.slice(1) : '')
}

function csvDateLabel(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-AU', { month: 'short', year: 'numeric' })
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function sinceLabel(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-AU', { month: 'short', year: 'numeric' })
}

// ---------------------------------------------------------------------------
// States
// ---------------------------------------------------------------------------

function LoadingState() {
  return (
    <div
      className="flex items-center gap-3 rounded-2xl px-6 py-8 text-[13.5px]"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW, color: INK_MUTED }}
    >
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      <span style={SERIF_ITALIC}>Gathering the world…</span>
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div
      className="rounded-2xl px-6 py-6 text-[13.5px]"
      style={{ background: '#FBF6F5', border: '1px solid rgba(214, 96, 87, 0.28)', color: '#8a3a33' }}
    >
      <p className="font-serif text-[16px]" style={{ color: '#8a3a33' }}>
        Something went wrong reaching the world.
      </p>
      <p className="mt-1 text-[13px]" style={{ ...SERIF_ITALIC, color: 'rgba(138, 58, 51, 0.72)' }}>
        {message}
      </p>
    </div>
  )
}

function EmptyWorld() {
  return (
    <div
      className="rounded-2xl px-10 py-16 text-center"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <p className="font-serif text-[22px] leading-tight md:text-[24px]" style={{ color: INK }}>
        No members have arrived yet.
      </p>
      <p className="mx-auto mt-3 max-w-[440px] text-[14px] leading-relaxed" style={SERIF_ITALIC}>
        When someone joins a collective, they&apos;ll appear here.
      </p>
    </div>
  )
}

function EmptyResults({ onClear }: { onClear: () => void }) {
  return (
    <div
      className="rounded-2xl px-10 py-14 text-center"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <p className="font-serif text-[20px] leading-tight" style={{ color: INK }}>
        No members match that search yet.
      </p>
      <button
        type="button"
        onClick={onClear}
        className="mt-4 rounded-full px-4 py-2 text-[12.5px] font-semibold transition-colors hover:bg-slate-50/60"
        style={{ border: '1px solid #E7EEF0', color: INK }}
      >
        Clear filters
      </button>
    </div>
  )
}
