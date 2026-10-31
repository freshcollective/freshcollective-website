'use client'

import type { Collective } from '@/lib/insights-history'
import { WM_HUE } from '@/lib/wm-palette'
import { humaniseClass } from '@/lib/insights'

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

/**
 * Which Collectives to compare.
 *
 * Capped at the number of chart hues, not at an arbitrary number. The
 * palette assigns four categorical colours in a fixed order and never
 * cycles, so a fifth line would either repeat a colour — two
 * Collectives indistinguishable on the chart — or invent one. Rather
 * than do either, the control stops offering more and says why.
 *
 * A Collective with no stored history is still listed, and marked. It
 * can be selected: an empty chart that says "nothing has been built
 * for this one" is a better answer than an absence the reader has to
 * interpret.
 */
export function CollectiveSelect({
  collectives,
  selected,
  onChange,
  max,
  disabled,
}: {
  collectives: Collective[]
  selected: string[]
  onChange: (next: string[]) => void
  max: number
  disabled?: boolean
}) {
  const atLimit = selected.length >= max

  function toggle(id: string) {
    if (selected.includes(id)) onChange(selected.filter((s) => s !== id))
    else if (!atLimit) onChange([...selected, id])
  }

  if (collectives.length === 0) {
    return (
      <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
        No Collectives in this classification.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="flex flex-wrap items-center gap-1.5"
        role="group"
        aria-label="Collectives to compare"
      >
        <span className="mr-0.5 text-[12px]" style={{ color: INK_MUTED }}>
          Comparing
        </span>
        {collectives.map((c) => {
          const active = selected.includes(c.id)
          const blocked = !active && atLimit
          return (
            <button
              key={c.id}
              type="button"
              disabled={disabled || blocked}
              aria-pressed={active}
              title={
                c.history_begins
                  ? `History from ${c.history_begins}`
                  : 'No reporting history has been built for this Collective yet'
              }
              onClick={() => toggle(c.id)}
              className="rounded-lg px-3 py-1.5 text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
              style={
                active
                  ? {
                      background: WM_HUE.teal.bg,
                      border: `1px solid ${WM_HUE.teal.border}`,
                      color: WM_HUE.teal.text,
                      fontWeight: 600,
                    }
                  : {
                      background: '#FFFFFF',
                      border: '1px solid #E7EEF0',
                      color: INK_MUTED,
                    }
              }
            >
              {c.name}
              {c.reporting_class && c.reporting_class !== 'production' && (
                <span className="ml-1.5 opacity-70">
                  {humaniseClass(c.reporting_class)}
                </span>
              )}
              {!c.history_begins && (
                <span className="ml-1.5 opacity-70">no history</span>
              )}
            </button>
          )
        })}
      </div>
      {atLimit && (
        <p className="text-[12px]" style={{ color: INK_MUTED }}>
          {max} at a time — the chart palette has {max} colours and never
          repeats one, so a {max + 1}th line could not be told from another.
          Deselect one to swap.
        </p>
      )}
      {selected.length === 0 && (
        <p className="text-[12px]" style={{ color: INK }}>
          Choose at least one Collective to draw the comparisons.
        </p>
      )}
    </div>
  )
}
