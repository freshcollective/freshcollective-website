/**
 * Explaining a discounted charge on the Creator Studio payment detail.
 *
 * Everything here is read from the transaction's immutable discount
 * snapshot, which the server derived at purchase time. Nothing is
 * recalculated: the amount paid is what the ledger says, and the saving is
 * what was recorded, not `original - paid` worked out afresh. A creator
 * asking "why is this $153?" needs the answer the purchase actually
 * recorded, not one reconstructed from a code that may since have changed.
 *
 * Returns null when the transaction carries no discount, which is every
 * transaction predating the feature — the caller then renders exactly what
 * it rendered before.
 */

import { formatMoneyCents } from './formatMoney.ts'

export interface DiscountedTransaction {
  currency: string
  gross_amount_cents: number
  discount_code?: string | null
  discount_original_amount_cents?: number | null
  discount_amount_cents?: number | null
  discount_type?: string | null
  discount_percent_bps?: number | null
}

export interface DiscountDisplay {
  /** "FAMILY50 · 50% off" — or just the code when the shape is unknown. */
  label: string
  originalAmount: string
  discountAmount: string
  amountPaid: string
}

/** "50% off" / "A$50.00 off" / null when neither shape is recorded. */
export function describeDiscountShape(
  t: DiscountedTransaction,
): string | null {
  if (t.discount_type === 'percentage' && t.discount_percent_bps != null) {
    // Basis points, so 5000 is 50%. Trailing zeros trimmed: "50% off",
    // not "50.00% off", but "12.5% off" keeps its half.
    const pct = t.discount_percent_bps / 100
    return `${Number.isInteger(pct) ? pct : Number(pct.toFixed(2))}% off`
  }
  if (t.discount_type === 'fixed_amount' && t.discount_amount_cents != null) {
    return `${formatMoneyCents(t.discount_amount_cents, t.currency)} off`
  }
  return null
}

export function describeTransactionDiscount(
  t: DiscountedTransaction,
): DiscountDisplay | null {
  // A code alone is not enough to render a breakdown — without the
  // original and the saving there is nothing to explain, and showing a
  // half-filled panel is worse than showing none.
  if (!t.discount_code) return null
  if (t.discount_original_amount_cents == null) return null
  if (t.discount_amount_cents == null) return null

  const shape = describeDiscountShape(t)
  return {
    label: shape ? `${t.discount_code} · ${shape}` : t.discount_code,
    originalAmount: formatMoneyCents(t.discount_original_amount_cents, t.currency),
    discountAmount: formatMoneyCents(t.discount_amount_cents, t.currency),
    // From the ledger, never derived by subtraction — a rounding
    // disagreement between the two would be invisible and wrong.
    amountPaid: formatMoneyCents(t.gross_amount_cents, t.currency),
  }
}
