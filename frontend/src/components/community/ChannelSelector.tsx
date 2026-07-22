'use client'

import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import Link from 'next/link'

/**
 * ChannelSelector — grouped, calm navigation of a collective's Channels.
 *
 * Layout:
 *   ▸ System row (unheaded)   — Start Here 🌱  Common Room 🏡
 *   ▸ PATHWAYS                — 🛤 …
 *   ▸ GATHERINGS              — 📅 …
 *   ▸ PRIVATE                 — 🔒 …
 *   ▸ OPEN DISCUSSIONS        — 💬 …
 *
 * Empty groups collapse. Server sends `group_label` per channel and
 * the shape is a one-line lookup here so future channel types slot in
 * with a single addition to `GROUP_ORDER`.
 *
 * Design rules:
 *  - No unread badges, no counts, no dots.
 *  - Icons are strictly type-driven (server-computed).
 *  - URL `?channel=<slug>` is the source of truth.
 */

export interface ChannelSummary {
  id: string
  slug: string
  name: string
  channel_type: string
  is_default: boolean
  is_system?: boolean
  is_archived: boolean
  icon_emoji: string | null
  group_label?: string | null
}

interface Props {
  channels: ChannelSummary[]
  activeSlug: string
}

// Order the group headings render in. Groups not listed here still
// render — appended alphabetically after the known ones — so the UI
// tolerates future channel types before this file catches up.
const GROUP_ORDER: string[] = [
  'PATHWAYS',
  'GATHERINGS',
  'PRIVATE',
  'OPEN DISCUSSIONS',
]

export default function ChannelSelector({ channels, activeSlug }: Props) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  function hrefFor(slug: string): string {
    const params = new URLSearchParams(searchParams.toString())
    params.set('channel', slug)
    return `${pathname}?${params.toString()}`
  }

  // Partition: `null` → system row; otherwise a group heading.
  const systemChannels = channels.filter((c) => c.group_label == null)
  const grouped = new Map<string, ChannelSummary[]>()
  for (const c of channels) {
    if (c.group_label == null) continue
    const arr = grouped.get(c.group_label) ?? []
    arr.push(c)
    grouped.set(c.group_label, arr)
  }
  const orderedGroupKeys = [
    ...GROUP_ORDER.filter((k) => grouped.has(k)),
    ...Array.from(grouped.keys()).filter((k) => !GROUP_ORDER.includes(k)).sort(),
  ]

  return (
    <nav aria-label="Channels" className="mb-5 flex flex-col gap-3">

      {systemChannels.length > 0 && (
        <ChannelRow
          channels={systemChannels}
          activeSlug={activeSlug}
          onNavigate={(slug) => router.push(hrefFor(slug), { scroll: false })}
          hrefFor={hrefFor}
        />
      )}

      {orderedGroupKeys.map((key) => {
        const list = grouped.get(key) ?? []
        if (list.length === 0) return null
        return (
          <div key={key}>
            <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.16em]"
               style={{ color: 'rgba(12,24,38,0.48)' }}>
              {key}
            </p>
            <ChannelRow
              channels={list}
              activeSlug={activeSlug}
              onNavigate={(slug) => router.push(hrefFor(slug), { scroll: false })}
              hrefFor={hrefFor}
            />
          </div>
        )
      })}
    </nav>
  )
}

function ChannelRow({
  channels, activeSlug, onNavigate, hrefFor,
}: {
  channels: ChannelSummary[]
  activeSlug: string
  onNavigate: (slug: string) => void
  hrefFor: (slug: string) => string
}) {
  return (
    <div
      className="flex flex-wrap gap-2 overflow-x-auto pb-0.5"
      style={{ scrollbarWidth: 'thin' }}
    >
      {channels.map((c) => {
        const active = c.slug === activeSlug
        return (
          <Link
            key={c.id}
            href={hrefFor(c.slug)}
            aria-current={active ? 'page' : undefined}
            onClick={(e) => {
              e.preventDefault()
              onNavigate(c.slug)
            }}
            className="group flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors"
            style={active
              ? { background: 'var(--fc-accent, #0d9488)', color: '#FFFFFF' }
              : {
                  background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
                  color: 'var(--fc-accent, #0f766e)',
                }}
          >
            {c.icon_emoji && <span aria-hidden="true">{c.icon_emoji}</span>}
            <span>{c.name}</span>
            {c.is_archived && (
              <span
                className="rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
                style={active
                  ? { background: 'rgba(255,255,255,0.20)', color: '#FFFFFF' }
                  : { background: 'rgba(212,176,72,0.14)', color: '#8A6A15' }}
              >
                Archived
              </span>
            )}
          </Link>
        )
      })}
    </div>
  )
}
