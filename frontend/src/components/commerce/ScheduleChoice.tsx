'use client'

import {
  paletteHex,
  rgbaFromHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'
import {
  scheduleKindLabel,
  scheduleShortDescription,
  scheduleTotalLine,
} from '@/lib/paymentPlan'
import PurchaseScheduleButton from './PurchaseScheduleButton'

/**
 * One way to pay for a Payment Option — "Pay in full · $180", or
 * "Weekly payments · $18/week" with the total underneath.
 *
 * Shared by the Gathering Series sidebar and the Collective joining
 * doors, because an Option offered in two places is one commitment
 * described one way. When an Option has more than one checkoutable
 * schedule these stack as siblings, so the member chooses rather than
 * having the surface pick for them.
 */

export interface PurchaseSchedule {
  id: string
  name: string
  schedule_type: string
  total_amount_cents: number
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  /** Single source of truth from the backend — a surface must not
   *  re-encode checkout policy. When false the schedule is not
   *  offered, however well it would render. */
  is_member_checkoutable: boolean
}

export default function ScheduleChoice({
  optionName,
  schedule,
  paymentOptionId,
  returnBase,
  palette,
  withDivider,
  ctaLabel,
}: {
  optionName: string
  schedule: PurchaseSchedule
  paymentOptionId: string
  /** Where the buyer returns after Stripe. */
  returnBase: string
  palette?: CollectivePaletteMeta | null
  withDivider: boolean
  /** Overrides the default label. The Series sidebar says "Join with
   *  Awaken"; a joining door says the same thing for a different
   *  reason, and a member who is already inside should not be told to
   *  join again. */
  ctaLabel?: string
}) {
  const primary = paletteHex('primary', palette ?? null) ?? '#0f766e'
  const line = rgbaFromHex(primary, 0.16)

  const kindLabel = scheduleKindLabel(schedule)
  const shortDesc = scheduleShortDescription(schedule)
  const totalLine = scheduleTotalLine(schedule)
  const label = ctaLabel ?? (
    schedule.schedule_type === 'recurring_installments'
      ? `Start payment plan · ${optionName}`
      : `Join with ${optionName}`
  )

  return (
    <div style={withDivider ? { borderTop: `1px solid ${line}`, paddingTop: 12 } : undefined}>
      <div className="mb-2">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[12px] font-medium text-navy-900">
            {kindLabel}
          </span>
          <span className="shrink-0 text-[13px] font-semibold text-navy-900">
            {shortDesc}
          </span>
        </div>
        {totalLine && (
          <p className="mt-0.5 text-right text-[11px] text-slate-500">
            {totalLine}
          </p>
        )}
      </div>
      <PurchaseScheduleButton
        returnBase={returnBase}
        paymentOptionId={paymentOptionId}
        paymentOptionScheduleId={schedule.id}
        label={label}
        palette={palette}
        schedule={schedule}
        optionName={optionName}
      />
    </div>
  )
}
