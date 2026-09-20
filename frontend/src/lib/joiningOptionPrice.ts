import { scheduleShortDescription } from './paymentPlan.ts'

/**
 * What a Payment Option costs, for the creator reviewing their doors.
 *
 * Derived from the published, checkoutable schedules and phrased
 * through the same shared formatter the public joining door and the
 * Series sidebar use — a creator should read the commitment in the
 * words their members will read it in.
 *
 * The Access & Visibility panel previously read
 * ``override_total_cents`` / ``calculated_total_cents`` off the
 * Option. Those are authoring fields and are ``NULL`` on every Option
 * authored through the commerce UI, where grants and schedules are the
 * source of truth. Three healthy $180–$378 options therefore reported
 * "No price set" beside a ticked checkbox, telling the creator their
 * configuration was broken at the moment it started working.
 *
 * Lives in ``lib`` rather than beside the form so the rule is
 * testable against a production-shaped row instead of only asserted
 * against source text.
 */

export interface JoiningOptionSchedule {
  schedule_type: string
  total_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  name: string
  /** The backend's answer. A surface must never re-decide what
   *  checkout will accept. */
  is_member_checkoutable: boolean
}

export interface JoiningOptionPriceInput {
  currency: string
  schedules?: JoiningOptionSchedule[] | null
  /** Option-level fallback, for the rare shape with no usable
   *  schedule. Server-derived from the legacy columns. */
  effective_price_cents?: number | null
}

export function joiningOptionPriceLabel(option: JoiningOptionPriceInput): string {
  const buyable = (option.schedules ?? []).filter((s) => s.is_member_checkoutable)
  if (buyable.length > 0) {
    return buyable.map(scheduleShortDescription).filter(Boolean).join(' or ')
  }

  // No schedule a member could complete. Fall back to the Option's own
  // figure so a price the creator entered is not hidden from them, and
  // let the purchasability line explain the state.
  const cents = option.effective_price_cents
  if (cents == null) return 'No price set'
  if (cents === 0) return 'Free'
  return `$${(cents / 100).toLocaleString('en-AU')} ${option.currency}`
}

export interface PurchasabilityInput {
  purchasability?: string | null
  purchasability_notes?: string[] | null
}

/**
 * Why an Option that looks published still cannot be sold.
 *
 * Surfaced so a creator ticking a door is not left to infer from a
 * price line that everything is fine. ``ready`` returns null — the
 * absence of a warning is the message.
 */
export function purchasabilityWarning(option: PurchasabilityInput): string | null {
  const state = option.purchasability
  if (!state || state === 'ready') return null

  const notes = (option.purchasability_notes ?? []).filter(Boolean)
  if (notes.length > 0) return notes.join(' ')
  if (state === 'configured_not_yet_checkoutable') {
    return 'Set up, but not purchasable by members right now.'
  }
  return 'Not currently purchasable — check this option in Payment Options.'
}
