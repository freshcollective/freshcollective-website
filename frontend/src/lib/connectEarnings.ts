/**
 * Presenting Connect earnings to a creator.
 *
 * The backend already decided the numbers and the status wording; this turns
 * them into the lines on the page. Pure, so the arithmetic that appears on
 * screen is unit-tested rather than inspected.
 *
 * Why the breakdown is shown per sale
 * ----------------------------------
 * A creator can read "Stripe's fee comes out first, then ours" and still not
 * know what they will actually receive. Three explicit lines against one real
 * sale answer that better than any percentage — and they add up, so nothing
 * looks unaccounted for.
 *
 * What is deliberately absent: Stripe account and transfer ids, attempt
 * counts, raw Stripe errors, and any outstanding-recovery amount. A creator
 * being chased for money should hear it from a person.
 */

import type { ConnectEarningRow, ConnectEarningsResponse } from '@/types/platform'

export function formatMoney(cents: number | null, currency: string): string {
  if (cents === null) return '—'
  const amount = (cents / 100).toFixed(2)
  return `${currency === 'AUD' ? 'A$' : `${currency} `}${amount}`
}

export interface EarningLine {
  label: string
  value: string
  /** Rendered as a deduction rather than a total. */
  isDeduction: boolean
  /** True when the figure is not yet exact. */
  pending: boolean
}

/**
 * The four lines that account for one sale.
 *
 * An unknown processing fee shows as "being confirmed" rather than as zero —
 * zero would be a claim about a real cost that has not been measured yet, and
 * it would make the lines fail to add up in the creator's favour.
 */
export function earningLines(row: ConnectEarningRow): EarningLine[] {
  const feeUnknown = row.processing_fee_cents === null
  return [
    {
      label: 'Sale',
      value: formatMoney(row.sale_amount_cents, row.currency),
      isDeduction: false,
      pending: false,
    },
    {
      label: 'Stripe’s processing fee',
      value: feeUnknown
        ? 'being confirmed'
        : `− ${formatMoney(row.processing_fee_cents, row.currency)}`,
      isDeduction: true,
      pending: feeUnknown,
    },
    {
      label: 'Fresh Collective’s platform fee',
      value: `− ${formatMoney(row.platform_fee_cents, row.currency)}`,
      isDeduction: true,
      pending: false,
    },
    {
      label: 'Your share',
      value: row.creator_amount_cents === null
        ? 'being confirmed'
        : formatMoney(row.creator_amount_cents, row.currency),
      isDeduction: false,
      pending: row.creator_amount_cents === null,
    },
  ]
}

/**
 * Whether the three parts of a sale actually account for it.
 *
 * Used by the tests rather than the page: if this is ever false, the creator is
 * being shown figures that do not add up, which is worse than showing fewer.
 */
export function linesReconcile(row: ConnectEarningRow): boolean {
  if (row.processing_fee_cents === null || row.creator_amount_cents === null) {
    return true   // nothing claimed yet, so nothing to reconcile
  }
  return (
    row.platform_fee_cents +
      row.processing_fee_cents +
      row.creator_amount_cents ===
    row.sale_amount_cents
  )
}

export interface EarningsHeadline {
  headline: string
  body: string
  /** Null when there is nothing yet. */
  sentTotal: string | null
  awaitingTotal: string | null
}

/**
 * The summary above the list.
 *
 * "Sent to Stripe" rather than "paid": a completed transfer reaches the
 * creator's Stripe balance, and Stripe pays their bank on its own schedule.
 */
export function earningsHeadline(
  data: ConnectEarningsResponse,
): EarningsHeadline {
  if (data.row_count === 0) {
    return {
      headline: 'No Stripe payouts yet',
      body:
        'Once your sales start going through Stripe, each one will appear here ' +
        'with its fees broken down.',
      sentTotal: null,
      awaitingTotal: null,
    }
  }
  const sales = data.row_count === 1 ? 'sale' : 'sales'
  return {
    headline: `${data.row_count} ${sales} through Stripe`,
    body:
      'Each sale below shows what was taken out and what was left for you.',
    sentTotal: formatMoney(data.sent_total_cents, data.currency),
    awaitingTotal: data.awaiting_total_cents > 0
      ? formatMoney(data.awaiting_total_cents, data.currency)
      : null,
  }
}

/** A short caption for an instalment row, or null for a one-off purchase. */
export function instalmentCaption(row: ConnectEarningRow): string | null {
  if (row.installment_number === null) return null
  return `Payment ${row.installment_number} of a payment plan`
}

/** Whether the row should read as money that came back. */
export function isReturned(row: ConnectEarningRow): boolean {
  return row.refunded_amount_cents > 0
}
