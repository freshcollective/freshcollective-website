'use client'

/**
 * The inventory. Every email Fresh Collective currently sends, grouped
 * by the part of the world it belongs to.
 *
 * System-controlled templates stay in the list rather than being
 * filtered out: an inventory with silent gaps is worse than one that
 * says "this exists and Fresh Collective owns it". They open to a
 * read-only view.
 *
 * Templates whose topic is not live never reach this page — the API
 * excludes them, computed from rollout config, so they appear on their
 * own if a topic is ever switched on.
 */

import { useMemo, useState } from 'react'
import {
  EMPTY_FILTERS, categoriesOf, filterTemplates, groupByCategory,
} from '@/lib/emailTemplates'
import type {
  Classification, ListFilters, TemplateListItem,
} from '@/lib/emailTemplates'
import {
  ClassificationPill, DeliveryPill, StalePill, StatePill,
} from './Bits'
import {
  CARD_BG, CARD_BORDER, CARD_SHADOW, FIELD_BORDER, INK, INK_MUTED,
  INK_SOFTER, SERIF_ITALIC,
} from './tokens'

const CLASSIFICATIONS: { value: Classification; label: string }[] = [
  { value: 'editable', label: 'Editable' },
  { value: 'partial', label: 'Partially editable' },
  { value: 'system', label: 'System controlled' },
]

export default function TemplateList({
  templates, onOpen,
}: {
  templates: TemplateListItem[]
  onOpen: (key: string) => void
}) {
  const [filters, setFilters] = useState<ListFilters>(EMPTY_FILTERS)
  const categories = useMemo(() => categoriesOf(templates), [templates])
  const visible = useMemo(
    () => filterTemplates(templates, filters), [templates, filters],
  )
  const groups = useMemo(() => groupByCategory(visible), [visible])

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={filters.search}
          onChange={(e) => setFilters({ ...filters, search: e.target.value })}
          placeholder="Search emails"
          aria-label="Search emails"
          className="w-full sm:w-64 rounded-lg px-3 py-2 text-[13px] outline-none focus:border-[#22a598]"
          style={{ border: FIELD_BORDER, color: INK, background: CARD_BG }}
        />
        <Chip
          active={filters.category === null}
          onClick={() => setFilters({ ...filters, category: null })}
        >
          All areas
        </Chip>
        {categories.map((c) => (
          <Chip
            key={c}
            active={filters.category === c}
            onClick={() => setFilters({ ...filters, category: c })}
          >
            {c}
          </Chip>
        ))}
        <span className="mx-1 hidden sm:block" style={{ color: INK_SOFTER }}>·</span>
        <Chip
          active={filters.classification === null}
          onClick={() => setFilters({ ...filters, classification: null })}
        >
          Any
        </Chip>
        {CLASSIFICATIONS.map((c) => (
          <Chip
            key={c.value}
            active={filters.classification === c.value}
            onClick={() => setFilters({ ...filters, classification: c.value })}
          >
            {c.label}
          </Chip>
        ))}
      </div>

      {visible.length === 0 && (
        <p className="text-[14px] py-8" style={SERIF_ITALIC}>
          No emails match that.
        </p>
      )}

      {groups.map(({ category, templates: rows }) => (
        <section key={category} className="flex flex-col gap-2">
          <h2
            className="text-[13px] font-semibold"
            style={{ color: INK_MUTED }}
          >
            {category}
          </h2>
          <div
            className="overflow-hidden rounded-xl"
            style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
          >
            {rows.map((t, i) => (
              <button
                key={t.template_key}
                type="button"
                onClick={() => onOpen(t.template_key)}
                className="flex w-full flex-col gap-1.5 px-4 py-3.5 text-left transition-colors hover:bg-[rgba(56,160,158,0.04)]"
                style={i > 0 ? { borderTop: '1px solid rgba(12,24,38,0.06)' } : undefined}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[14px] font-semibold" style={{ color: INK }}>
                    {t.display_name}
                  </span>
                  <ClassificationPill value={t.classification} />
                  {t.editable && <StatePill customised={t.customised} />}
                  <DeliveryPill transactional={t.is_transactional} />
                  {t.has_stale_default && <StalePill />}
                </div>
                <span className="text-[13px]" style={{ color: INK_MUTED }}>
                  {t.audience}
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function Chip({
  active, onClick, children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors"
      style={
        active
          ? {
              background: 'rgba(56, 160, 158, 0.10)',
              border: '1px solid rgba(56, 160, 158, 0.30)',
              color: '#0f766e',
            }
          : {
              background: 'transparent',
              border: '1px solid rgba(12, 24, 38, 0.12)',
              color: INK_MUTED,
            }
      }
    >
      {children}
    </button>
  )
}
