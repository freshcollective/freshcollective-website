'use client'

import { PERIOD_OPTIONS, type PeriodKey } from '@/lib/insights'
import { WM_HUE } from '@/lib/wm-palette'

const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

/**
 * The reporting period, shared by every World Insights page.
 *
 * One component rather than a select per page, so "this month" means the
 * same span everywhere — the periods come from the backend's Australian
 * calendar, including the financial year, and a page that rolled its own
 * would be the first step back towards two surfaces disagreeing.
 */
export function PeriodSelect({
  value,
  onChange,
  disabled,
}: {
  value: PeriodKey
  onChange: (next: PeriodKey) => void
  disabled?: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Reporting period">
      {PERIOD_OPTIONS.map(([key, label]) => {
        const active = key === value
        return (
          <button
            key={key}
            type="button"
            disabled={disabled}
            aria-pressed={active}
            onClick={() => onChange(key)}
            className="rounded-lg px-3 py-1.5 text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
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
            {label}
          </button>
        )
      })}
    </div>
  )
}
