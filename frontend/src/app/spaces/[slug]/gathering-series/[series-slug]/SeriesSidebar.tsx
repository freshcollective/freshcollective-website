import Link from 'next/link'
import SeriesPurchaseButton from './SeriesPurchaseButton'
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

/**
 * Sidebar for the member Series page — either the member's
 * current access summary or a compact list of Ways to join.
 *
 * The full-width Payment Option cards on the previous pass were
 * far too dense for a 320px column; this file provides a
 * narrower single-column card design tuned for the sidebar.
 * Nothing here talks to the backend — data is hydrated by the
 * server page and passed in.
 */

interface AccessSummary {
  has_access: boolean
  option_name: string | null
  valid_from: string | null
  valid_until: string | null
  gatherings_per_week: number | null
  gatherings_total: number | null
  gatherings_used: number | null
  gatherings_remaining: number | null
  used_this_week: number | null
}

export interface SidebarPaymentSchedule {
  id: string
  name: string
  schedule_type: string
  total_amount_cents: number
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  /** Single source of truth from the backend — the sidebar must not
   *  re-encode checkout policy. When this is false the schedule is
   *  hidden from members even if it renders fine visually. */
  is_member_checkoutable: boolean
}

export interface SidebarPaymentOption {
  id: string
  name: string
  description: string | null
  allowance_per_week: number | null
  allowance_total: number | null
  included_titles: string[]
  schedules: SidebarPaymentSchedule[]
  viewer_holds_this_option: boolean
}

function formatShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

function formatMoney(cents: number, currency: string): string {
  const symbol = currency === 'AUD' || currency === 'USD' ? '$' : `${currency} `
  const dollars = cents / 100
  return `${symbol}${Number.isInteger(dollars) ? dollars : dollars.toFixed(2)}`
}

// ---------------------------------------------------------------------------
// Your access (member already holds a Series pass)
// ---------------------------------------------------------------------------

export function SidebarYourAccess({
  access, palette,
}: {
  access: AccessSummary
  palette: CollectivePaletteMeta | null
}) {
  const primary = paletteHex('primary', palette) ?? '#0f766e'
  const eyebrowColour = primary
  const borderColour = rgbaFromHex(primary, 0.24)
  const bgColour = rgbaFromHex(primary, 0.05)
  const validFromStr = access.valid_from ? formatShortDate(access.valid_from) : null
  const validUntilStr = access.valid_until ? formatShortDate(access.valid_until) : null
  const validity = validFromStr && validUntilStr
    ? `${validFromStr} – ${validUntilStr}`
    : validFromStr ? `From ${validFromStr}` : null

  return (
    <div
      className="rounded-2xl border px-5 py-5"
      style={{ borderColor: borderColour, background: bgColour }}
    >
      <p
        className="text-[10.5px] font-semibold uppercase tracking-[0.14em]"
        style={{ color: eyebrowColour }}
      >
        Your access
      </p>
      <p className="mt-1 font-serif text-lg text-navy-900">
        {access.option_name ?? 'Series access'}
      </p>
      {validity && <p className="mt-0.5 text-[12px] text-slate-600">{validity}</p>}

      {(access.gatherings_per_week != null || access.gatherings_total != null) && (
        <ul className="mt-4 space-y-2 text-[13px] text-navy-900">
          {access.gatherings_per_week != null && (
            <li className="flex items-baseline justify-between gap-3">
              <span className="text-slate-600">Each week</span>
              <span className="font-medium">
                {access.used_this_week != null
                  ? `${access.used_this_week} of ${access.gatherings_per_week}`
                  : `${access.gatherings_per_week}`}
              </span>
            </li>
          )}
          {access.gatherings_total != null && (
            <li className="flex items-baseline justify-between gap-3">
              <span className="text-slate-600">In total</span>
              <span className="font-medium">
                {access.gatherings_used != null
                  ? `${access.gatherings_used} of ${access.gatherings_total}`
                  : `${access.gatherings_total}`}
              </span>
            </li>
          )}
          {access.gatherings_remaining != null && (
            <li className="flex items-baseline justify-between gap-3">
              <span className="text-slate-600">Remaining</span>
              <span className="font-semibold" style={{ color: primary }}>
                {access.gatherings_remaining}
              </span>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Ways to join (member doesn't hold a pass)
// ---------------------------------------------------------------------------

export function SidebarWaysToJoin({
  spaceSlug, seriesSlug, options, hasPurchasable, palette,
}: {
  spaceSlug: string
  seriesSlug: string
  options: SidebarPaymentOption[]
  hasPurchasable: boolean
  palette: CollectivePaletteMeta | null
}) {
  const primary = paletteHex('primary', palette) ?? '#0f766e'
  // Only surface options that (a) the viewer doesn't already hold
  // and (b) have at least one member-checkoutable schedule. The
  // second filter mirrors ``CompactOptionCard``'s own guard so we
  // never render an empty <li>.
  const available = options.filter(
    (o) => !o.viewer_holds_this_option
      && o.schedules.some((s) => s.is_member_checkoutable),
  )
  const held = options.filter((o) => o.viewer_holds_this_option)

  if (!hasPurchasable && options.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-5 py-6 text-center">
        <p className="text-[13px] font-medium text-navy-900">Ways to join are coming soon.</p>
        <p className="mt-1 text-[12px] leading-relaxed text-slate-600">
          The Creator hasn&rsquo;t published a Payment Option for this Series yet.
        </p>
      </div>
    )
  }

  return (
    <div>
      <p
        className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
        style={{ color: primary }}
      >
        Ways to join
      </p>

      <ul className="space-y-3">
        {available.map((o) => (
          <li key={o.id}>
            <CompactOptionCard
              spaceSlug={spaceSlug}
              seriesSlug={seriesSlug}
              option={o}
              palette={palette}
            />
          </li>
        ))}
      </ul>

      {held.length > 0 && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[12px] leading-relaxed text-slate-600">
          You already hold: <strong>{held.map((o) => o.name).join(', ')}</strong>.
          Contact the Creator to change your plan.
        </div>
      )}
    </div>
  )
}

function CompactOptionCard({
  spaceSlug, seriesSlug, option, palette,
}: {
  spaceSlug: string
  seriesSlug: string
  option: SidebarPaymentOption
  palette: CollectivePaletteMeta | null
}) {
  const primary = paletteHex('primary', palette) ?? '#0f766e'
  const primary_border = rgbaFromHex(primary, 0.14)
  const primary_soft = rgbaFromHex(primary, 0.06)

  // Only render schedules the backend flagged member-checkoutable.
  // Draft rows and recurring-instalment rows (deferred to the
  // Commerce milestone) never surface to members here. The card
  // shape is intentionally multi-schedule ready: when instalments
  // land, the same layout renders both "Pay in full" and
  // "$X/week × N" side by side without further refactor.
  const buyable = option.schedules.filter((s) => s.is_member_checkoutable)
  if (buyable.length === 0) return null

  const allowanceLine = [
    option.allowance_per_week != null ? `${option.allowance_per_week}/week` : null,
    option.allowance_total != null ? `${option.allowance_total} total` : null,
  ].filter(Boolean).join(' · ')

  // "Includes" — Series is always first (implicit); other titles
  // are usually a bundled Pathway or two. Keep to at most two
  // items so the card doesn't grow tall.
  const otherIncludes = option.included_titles.slice(1, 3)

  return (
    <div
      className="rounded-2xl border p-4"
      style={{ borderColor: primary_border, background: primary_soft }}
    >
      <h3 className="font-serif text-[16px] text-navy-900">{option.name}</h3>

      {allowanceLine && (
        <p className="mt-1 text-[12.5px] text-slate-600">{allowanceLine}</p>
      )}

      {otherIncludes.length > 0 && (
        <p className="mt-2 text-[12px] text-slate-600">
          <span className="text-slate-500">Also includes: </span>
          {otherIncludes.join(', ')}
        </p>
      )}

      <div className="mt-3 space-y-3">
        {buyable.map((s, i) => (
          <ScheduleChoice
            key={s.id}
            optionName={option.name}
            schedule={s}
            spaceSlug={spaceSlug}
            seriesSlug={seriesSlug}
            paymentOptionId={option.id}
            palette={palette}
            withDivider={i > 0}
          />
        ))}
      </div>
    </div>
  )
}

/** One purchasable payment method inside a Payment Option. Renders
 *  as "Method label · price line" over the top of the CTA button.
 *  When multiple methods exist ("Pay in full" and "$20/week × 10")
 *  they stack with a soft divider so the member scans them as
 *  siblings under the same Option (Awaken). */
function ScheduleChoice({
  optionName, schedule, spaceSlug, seriesSlug, paymentOptionId,
  palette, withDivider,
}: {
  optionName: string
  schedule: SidebarPaymentSchedule
  spaceSlug: string
  seriesSlug: string
  paymentOptionId: string
  palette: CollectivePaletteMeta | null
  withDivider: boolean
}) {
  const primary = paletteHex('primary', palette) ?? '#0f766e'
  const line = rgbaFromHex(primary, 0.16)

  const kindLabel = scheduleKindLabel(schedule)
  const shortDesc = scheduleShortDescription(schedule)
  const totalLine = scheduleTotalLine(schedule)
  const ctaLabel =
    schedule.schedule_type === 'recurring_installments'
      ? `Start payment plan · ${optionName}`
      : `Join with ${optionName}`

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
      <SeriesPurchaseButton
        spaceSlug={spaceSlug}
        seriesSlug={seriesSlug}
        paymentOptionId={paymentOptionId}
        paymentOptionScheduleId={schedule.id}
        label={ctaLabel}
        palette={palette}
      />
    </div>
  )
}
