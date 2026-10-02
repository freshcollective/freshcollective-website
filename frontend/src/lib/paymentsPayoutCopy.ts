/**
 * Payout copy for Creator Studio → Payments received, by payout model.
 *
 * Pure, so the wording is unit-testable under Node's test runner and so
 * the strings sit somewhere a test can assert what they must never say
 * again.
 *
 * What was wrong
 * --------------
 * The page told every creator that "automatic payouts via Stripe Connect
 * are coming in a future update — for now, payouts are handled manually",
 * and that they "do not need to connect your own Stripe account". Both
 * were rendered unconditionally. For a creator whose sales already route
 * through Connect — whose money has already moved — both are false, and
 * the second contradicts the Billing page that asked them to connect.
 *
 * The rule here
 * -------------
 * Copy follows the *rows*, not a global flag. A creator can have manual
 * history and Connect sales at once, because ``payout_model`` is frozen
 * onto each transaction when it is created and never re-derived. So the
 * note describes what is actually in the list.
 *
 * Wording discipline
 * ------------------
 * Never "paid out" and never "paid" for a Connect transfer. A completed
 * transfer reaches the creator's *Stripe balance*; Stripe pays their bank
 * on its own schedule, and those are different events. The backend
 * composes the per-sale label ("Sent to Stripe", "Preparing payout",
 * "Needs attention") in ``connect_earnings.STATUS_LABELS`` and this
 * module does not second-guess it.
 */

export type PayoutMix = 'none' | 'manual_only' | 'connect_only' | 'mixed'

export interface PayoutNote {
  /** The sentence under the transactions table. */
  body: string
  /** Whether to show the "you don't need your own Stripe account" card. */
  showNoStripeNeededCard: boolean
}

/* Platform-owned Collectives are handled by the caller before reaching
 * here — they have no creator payout at all, and their note carries its
 * own emphasis that a plain string would lose. */

export interface PayoutModelRow {
  payout_model?: string | null
}

/** What payout models actually appear in the rows on screen. */
export function payoutMix(rows: PayoutModelRow[] | null | undefined): PayoutMix {
  const list = rows ?? []
  if (list.length === 0) return 'none'
  let manual = false
  let connect = false
  for (const row of list) {
    if (row.payout_model === 'connect') connect = true
    else manual = true
  }
  if (connect && manual) return 'mixed'
  if (connect) return 'connect_only'
  return 'manual_only'
}

const MANUAL_SENTENCE =
  'Your creator earnings are tracked as pending payout and are paid to you ' +
  'by Fresh Collective.'

const CONNECT_SENTENCE =
  'Your share of each sale is transferred to your own Stripe account. ' +
  '“Sent to Stripe” means the transfer has left Fresh Collective — Stripe ' +
  'then pays it into your bank account on its own schedule.'

/**
 * The note under the table.
 *
 * The "no Stripe account needed" card is suppressed the moment a single
 * Connect row exists. It is the claim most likely to be read as
 * instruction, and a creator who has already connected Stripe being told
 * they needn't have is worse than saying nothing.
 */
export function payoutNote(
  rows: PayoutModelRow[] | null | undefined,
  options: { feeDisplay?: string | null } = {},
): PayoutNote {
  const fee = options.feeDisplay
    ? ` Your transaction fee is ${options.feeDisplay} per sale.`
    : ''

  switch (payoutMix(rows)) {
    case 'connect_only':
      return { body: CONNECT_SENTENCE + fee, showNoStripeNeededCard: false }
    case 'mixed':
      return {
        // Named explicitly rather than averaged: a creator looking at two
        // rows that settled differently needs to know the list is mixed,
        // not be told one story that is wrong for half of it.
        body:
          CONNECT_SENTENCE +
          ' Sales from before your account was connected are still paid to ' +
          'you by Fresh Collective.' + fee,
        showNoStripeNeededCard: false,
      }
    case 'manual_only':
    case 'none':
    default:
      return { body: MANUAL_SENTENCE + fee, showNoStripeNeededCard: true }
  }
}

/**
 * The "how you're paid" block on the Billing page.
 *
 * Driven by ``connect_routing_enabled`` rather than by the transaction
 * list, because this block sits beside the Connect panel and answers
 * "what happens to my sales from now on" — a forward-looking question
 * the rows cannot answer on their own. The Payments page answers the
 * backward-looking one from the rows themselves.
 *
 * What was wrong
 * --------------
 * It read "Phase 1 — current … earnings are tracked as pending payout
 * and disbursed manually", with a "Coming later" list whose first two
 * entries were automatic Stripe payouts and refunds. Both had shipped,
 * and the block rendered directly above the live earnings list showing
 * real transfers marked "Sent to Stripe". A creator was being told the
 * thing in front of them did not exist yet.
 *
 * Refunds and payout reporting are dropped from "Coming later" rather
 * than reworded: that line bundled shipped work with unshipped, and a
 * roadmap entry that is half true is worse than one fewer line. GST and
 * tax reporting genuinely is not built, so it stays.
 */
export interface BillingPayoutPhase {
  title: string
  body: string
  comingLater: string[]
}

export function billingPayoutPhase(
  routingEnabled: boolean | null | undefined,
): BillingPayoutPhase {
  if (routingEnabled) {
    return {
      title: 'How you’re paid',
      body:
        CONNECT_SENTENCE +
        ' Sales from before your account was connected are still paid to ' +
        'you by Fresh Collective.',
      comingLater: ['GST/tax reporting and invoicing'],
    }
  }
  return {
    title: 'How you’re paid',
    body:
      'Payments are processed through the Fresh Collective Stripe account. ' +
      MANUAL_SENTENCE +
      ' Connecting Stripe above prepares your account for automatic ' +
      'payouts, and we’ll tell you before your sales start using it.',
    comingLater: [
      'Automatic payouts of your sales through Stripe',
      'GST/tax reporting and invoicing',
    ],
  }
}
