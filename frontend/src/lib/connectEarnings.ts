/**
 * Presenting Connect earnings to a creator.
 *
 * The backend already decided the numbers and the status wording; this turns
 * them into the lines on the page. Pure, so the arithmetic that appears on
 * screen is unit-tested rather than inspected.
 *
 * Why the breakdown is shown per sale
 * ----------------------------------
 * A creator can read "we take 8%" and still not know what they will actually
 * receive. Explicit lines against one real sale answer that better than any
 * percentage — and they add up, so nothing looks unaccounted for.
 *
 * Two fee models, both real
 * -------------------------
 * Fresh Collective now absorbs the card processing cost, so a creator's
 * earnings are ``sale - commission`` and the processing fee is a cost FC
 * carried, not a deduction from them.
 *
 * A handful of sales were transferred before that change, under
 * ``sale - commission - processing``. Those transfers really were smaller.
 * Presenting them under today's rule would tell a creator they received money
 * they never got, so each row is read on its own terms: see
 * :func:`earningsBasis`, which decides which rule a row was priced under and
 * refuses to guess when neither fits.
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
  /**
   * Shown for transparency but outside the creator's own arithmetic — a cost
   * Fresh Collective carried. Rendered quietly and never with a minus sign,
   * because a minus sign is a claim that it came out of their money.
   */
  covered?: boolean
}

/**
 * Which rule a row's creator figure was priced under.
 *
 * ``commission_only``           today's policy: sale - commission.
 * ``commission_and_processing`` a transfer sent before Fresh Collective began
 *                              absorbing the processing fee.
 * ``not_yet_priced``            no creator figure recorded yet.
 * ``unreconciled``              the figures do not account for the sale under
 *                              either rule.
 */
export type EarningsBasis =
  | 'commission_only'
  | 'commission_and_processing'
  | 'not_yet_priced'
  | 'unreconciled'

/**
 * Decide, from the figures alone, which rule priced this row.
 *
 * Deliberately not "does it match today's rule, and shrug if not". Both rules
 * are checked explicitly, so a historical transfer is recognised as correct
 * rather than tolerated as a discrepancy — and a row that matches *neither*
 * is reported, rather than being quietly absorbed into whichever branch
 * happened to be last.
 *
 * ``commission_only`` is tested first so a zero processing fee — where the
 * two rules coincide — resolves to today's policy rather than by accident.
 */
export function earningsBasis(row: ConnectEarningRow): EarningsBasis {
  const creator = row.creator_amount_cents
  if (creator === null) return 'not_yet_priced'

  const afterCommission = row.sale_amount_cents - row.platform_fee_cents
  if (creator === afterCommission) return 'commission_only'

  if (
    row.processing_fee_cents !== null &&
    creator === afterCommission - row.processing_fee_cents
  ) {
    return 'commission_and_processing'
  }
  return 'unreconciled'
}

/**
 * The lines that account for one sale, under the rule that priced it.
 *
 * An unknown processing fee shows as "being confirmed" rather than as zero —
 * zero would be a claim about a real cost that has not been measured yet.
 * Under today's policy that gap is harmless to the creator, because their
 * earnings never depended on it.
 */
export function earningLines(row: ConnectEarningRow): EarningLine[] {
  const basis = earningsBasis(row)
  const feeUnknown = row.processing_fee_cents === null
  const processing = feeUnknown
    ? 'being confirmed'
    : formatMoney(row.processing_fee_cents, row.currency)

  const sale: EarningLine = {
    label: 'Sale',
    value: formatMoney(row.sale_amount_cents, row.currency),
    isDeduction: false,
    pending: false,
  }
  const commission: EarningLine = {
    label: 'Fresh Collective commission',
    value: `− ${formatMoney(row.platform_fee_cents, row.currency)}`,
    isDeduction: true,
    pending: false,
  }

  if (basis === 'commission_and_processing') {
    // Sent before Fresh Collective began covering card processing. The fee
    // genuinely was deducted from this transfer, so it is shown as the
    // deduction it was. Relabelling it "we cover this" would be false about
    // a payment that has already happened.
    return [
      sale,
      {
        label: 'Card processing fee',
        value: `− ${processing}`,
        isDeduction: true,
        pending: feeUnknown,
      },
      commission,
      {
        label: 'Transferred to you',
        value: formatMoney(row.creator_amount_cents, row.currency),
        isDeduction: false,
        pending: false,
      },
    ]
  }

  const earnings: EarningLine = {
    label: 'Your earnings',
    value: row.creator_amount_cents === null
      ? 'being confirmed'
      : formatMoney(row.creator_amount_cents, row.currency),
    isDeduction: false,
    pending: row.creator_amount_cents === null,
  }

  if (basis === 'unreconciled') {
    // The figures do not account for the sale under either rule. Showing a
    // breakdown that visibly fails to add up is worse than showing less, so
    // the breakdown is withheld and the two figures FC can stand behind are
    // shown alone. ``linesReconcile`` reports this for the tests.
    return [sale, earnings]
  }

  return [
    sale,
    commission,
    earnings,
    {
      label: 'Card processing — Fresh Collective covers this',
      value: processing,
      isDeduction: false,
      pending: feeUnknown,
      covered: true,
    },
  ]
}

/**
 * Whether the parts of a sale actually account for it.
 *
 * Used by the tests rather than the page: if this is ever false, the creator
 * is being shown figures that do not add up, which is worse than showing
 * fewer — and :func:`earningLines` withholds the breakdown when it happens.
 *
 * True for a row priced under either rule, and for one not yet priced.
 * A historical transfer is *reconciled*, not excused: it satisfies the older
 * rule exactly. Only a row matching neither is false.
 */
export function linesReconcile(row: ConnectEarningRow): boolean {
  return earningsBasis(row) !== 'unreconciled'
}

/**
 * A plain sentence for a row whose figures need explaining, or null.
 *
 * Only historical transfers need one: their creator figure is lower than
 * today's rule would give, and without a reason that reads like an error.
 */
export function earningsBasisNote(row: ConnectEarningRow): string | null {
  if (earningsBasis(row) !== 'commission_and_processing') return null
  return (
    'This sale was paid out before Fresh Collective began covering card ' +
    'processing costs, so the fee was taken out of the transfer. Sales ' +
    'since then are not reduced by it.'
  )
}

export interface EarningsHeadline {
  headline: string
  body: string
  /** Null when there is nothing yet. */
  sentTotal: string | null
  /**
   * Transfers not yet sent. Deliberately NOT called "earned": the backend
   * total covers both ``pending`` (the customer has paid, the transfer is
   * owed) and ``awaiting_payment`` (the customer has not paid yet — an
   * uncollected instalment, which may never arrive). Calling that earned
   * would promise a creator money Fresh Collective does not hold.
   *
   * Splitting the two would need a new summary field; see the note in the
   * implementation report.
   */
  awaitingTotal: string | null
}

/**
 * The summary above the list.
 *
 * "Released for payout" rather than "paid" or "on its way": a completed
 * transfer reaches the creator's Stripe balance, and the bank payout happens
 * afterwards on its own schedule.
 *
 * Not "on its way" either, which this said first. A transfer stays ``sent``
 * after its money has reached the bank, so that total described A$3.02 as in
 * transit when A$1.51 of it had already been paid. "Released" is true of
 * every sent transfer whatever the bank has since done with it — and the
 * payout list below now shows exactly which amounts have arrived.
 */
export function earningsHeadline(
  data: ConnectEarningsResponse,
): EarningsHeadline {
  if (data.row_count === 0) {
    return {
      headline: 'No earnings yet',
      body:
        'Once you make a sale, it will appear here with your earnings and ' +
        'what Fresh Collective kept broken down.',
      sentTotal: null,
      awaitingTotal: null,
    }
  }
  const sales = data.row_count === 1 ? 'sale' : 'sales'
  return {
    headline: `${data.row_count} ${sales}`,
    body:
      'Each sale below shows your earnings and the commission Fresh ' +
      'Collective kept. Card processing is shown too — we cover that.',
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
