/**
 * Presenting a creator's bank account and their actual bank payouts.
 *
 * Pure, so the words and the figures that appear on screen are unit-tested
 * rather than inspected.
 *
 * The distinction this file exists to hold
 * ----------------------------------------
 * A Connect transfer moves a creator's share into their Stripe balance. A
 * payout is the separate, later step where Stripe sends that balance to
 * their bank. Nothing here may describe the first as the second: a transfer
 * can succeed and a bank deposit fail days afterwards, and only Stripe's
 * ``paid`` status means the money arrived.
 */

import type {
  CreatorBankPayout,
  CreatorStripeConnectStatus,
} from '@/types/platform'

export function formatPayoutMoney(cents: number, currency: string): string {
  const amount = (cents / 100).toFixed(2)
  return `${currency === 'AUD' ? 'A$' : `${currency} `}${amount}`
}

/** A date a creator can read, or null when Stripe has given us none. */
export function formatPayoutDate(iso: string | null): string | null {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export interface BankAccountView {
  /** True once Stripe has told us a bank account is attached. */
  present: boolean
  /** "Commonwealth Bank •••• 4321", or a plain statement of the state. */
  label: string
  /** The reassurance that Fresh Collective never sees the full number. */
  note: string
  /** "Update bank details" once one exists, "Add bank details" before. */
  actionLabel: string
  /**
   * True when a bank account exists but its masked details have not been
   * read yet. The page says so rather than guessing either way.
   */
  detailsPending: boolean
}

/**
 * The creator's nominated bank account.
 *
 * Existence and masked details are two separate facts, and conflating them
 * caused a live defect: a creator whose account Stripe had confirmed — with
 * payouts active and a payout already paid — was told "No bank account added
 * yet" and invited to add one, purely because Fresh Collective had not yet
 * read the last four digits.
 *
 * So existence is keyed on ``external_account_count``, which Stripe reports
 * on every sync and which was correct throughout that incident. The masked
 * details only decide how precisely the account can be *described*.
 */
export function bankAccountView(
  status: CreatorStripeConnectStatus | null,
): BankAccountView {
  const exists = (status?.external_account_count ?? 0) > 0
  const last4 = status?.bank_last4 ?? null

  if (!exists) {
    return {
      present: false,
      detailsPending: false,
      label: 'No bank account added yet',
      note:
        'Add your bank details to receive your earnings. Stripe collects '
        + 'them directly — Fresh Collective never sees your account number.',
      actionLabel: 'Add bank details',
    }
  }

  const heldSecurely =
    'Your bank details are held securely by Stripe. Fresh Collective never '
    + 'sees your full account number.'

  if (!last4) {
    // The account is there; we simply have not read its details yet. Saying
    // "no bank account" here would be false, and inviting them to add one
    // would send them to change something that is already correct.
    return {
      present: true,
      detailsPending: true,
      label: 'Your bank account is set up. We’re confirming the details with Stripe.',
      note: heldSecurely,
      actionLabel: 'Update bank details',
    }
  }

  const name = status?.bank_name?.trim()
  return {
    present: true,
    detailsPending: false,
    label: `${name ? `${name} ` : ''}•••• ${last4}`,
    note: heldSecurely,
    actionLabel: 'Update bank details',
  }
}

/**
 * What each Stripe payout status means, in plain words.
 *
 * ``paid`` is the only one that says the money arrived. The others are
 * deliberately phrased so none of them could be mistaken for it.
 */
export const PAYOUT_STATUS_LABELS: Record<CreatorBankPayout['status'], string> = {
  pending: 'Preparing',
  in_transit: 'On its way to your bank',
  paid: 'Paid into your bank',
  failed: 'Didn’t go through',
  canceled: 'Cancelled',
}

export interface PayoutRowView {
  amount: string
  status: string
  /** "Expected 13 Oct 2026" / "Paid 13 Oct 2026", or null. */
  when: string | null
  /** True for the one status that means it arrived. */
  arrived: boolean
  /** True when it needs attention. */
  attention: boolean
  /**
   * What the creator should do, or null when there is nothing for them to
   * do. Only a failed payout asks anything of them — a cancelled one is
   * almost always Fresh Collective's or Stripe's doing, and telling someone
   * to act when they cannot is worse than saying nothing.
   */
  action: string | null
}

export function payoutRowView(payout: CreatorBankPayout): PayoutRowView {
  const date = formatPayoutDate(payout.arrival_date)
  const arrived = payout.status === 'paid'
  // Past tense only once it has actually happened. "Paid 13 Oct" for a
  // payout still in transit would be the single most misleading thing on
  // the page.
  const when = date
    ? arrived ? `Paid ${date}` : `Expected ${date}`
    : null
  return {
    amount: formatPayoutMoney(payout.amount_cents, payout.currency),
    status: PAYOUT_STATUS_LABELS[payout.status] ?? 'Being confirmed',
    when,
    arrived,
    attention: payout.status === 'failed',
    // A failed payout is nearly always a bank detail Stripe could not use,
    // and the money stays in the creator's Stripe balance rather than
    // disappearing — worth saying, because "didn't go through" otherwise
    // reads as money lost. A cancelled payout needs nothing from them.
    action: payout.status === 'failed'
      ? 'Check your bank details below — your money is still with Stripe and '
        + 'will be sent again once they are correct.'
      : null,
  }
}

export interface PayoutsHeadline {
  headline: string
  body: string
}

/**
 * The words above the payout list.
 *
 * An empty list is the common case early on, and it has two quite different
 * causes: no bank account yet, or a bank account with no payout made so far.
 * Saying which one it is saves a creator guessing.
 */
export function payoutsHeadline(
  payouts: CreatorBankPayout[],
  status: CreatorStripeConnectStatus | null,
): PayoutsHeadline {
  if (payouts.length > 0) {
    return {
      headline: 'Your payouts',
      body:
        'Money Stripe has sent to your bank. Only “Paid into your bank” '
        + 'means it has arrived.',
    }
  }
  if (!bankAccountView(status).present) {
    return {
      headline: 'No payouts yet',
      body: 'Once your bank details are added, your payouts will appear here.',
    }
  }
  return {
    headline: 'No payouts yet',
    body:
      'Your bank details are set up. Your first payout will appear here '
      + 'once Stripe sends it.',
  }
}

/**
 * Whether the list can be described as the creator's whole history.
 *
 * The import walks backwards through Stripe a page at a time, so for a while
 * the list is genuinely partial. Saying so is the point: a partial history
 * presented as complete would have a creator conclude a payout never
 * happened.
 */
export function historyNote(
  historyComplete: boolean,
  payoutCount: number,
): string | null {
  if (historyComplete) return null
  if (payoutCount === 0) {
    return 'We’re still importing your payout history from Stripe. '
      + 'Anything already sent will appear here shortly.'
  }
  return 'We’re still importing your older payouts from Stripe, so this list '
    + 'may not be complete yet.'
}

/**
 * How current the list is.
 *
 * Shown rather than hidden, because the list is a copy of Stripe's records
 * read on a schedule, not a live view — and implying otherwise would make a
 * missing recent payout look like a lost one.
 */
export function payoutsFreshness(syncedAt: string | null): string | null {
  const when = formatPayoutDate(syncedAt)
  return when ? `Checked with Stripe on ${when}` : null
}
