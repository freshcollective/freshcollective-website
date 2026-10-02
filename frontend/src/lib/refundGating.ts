/**
 * Who may refund a transaction, and what they must be told first.
 *
 * Pure, so the policy is unit-testable under Node's test runner and so
 * it sits somewhere a test can hold it against the backend's.
 *
 * This mirrors ``_payout_gate_action`` / ``_connect_gate_action`` in
 * ``backend/app/creator/refund_routes.py``. The backend is the
 * authority — it refuses regardless of what this returns. What this
 * decides is whether the button is offered, and the two disagreeing is
 * its own kind of defect: a visible button that 403s, or a refund the
 * policy allows that nobody can reach.
 *
 * Connect rows after the transfer
 * -------------------------------
 * ``sent`` and ``partially_reversed`` are refundable by the authorised
 * creator-owner, not only by an admin. The customer refund commits
 * first and the reversal follows as a separate step that cannot fail
 * it; if the connected account cannot cover the clawback the row
 * records ``connect_recovery_state = required`` with the exact
 * shortfall. So the money FC might be owed is tracked rather than
 * prevented, and a creator is not blocked from refunding their own
 * sale. ``isPlatformOwner`` therefore does not gate Connect rows at
 * all — it still gates manual ``paid`` / ``held`` ones, which have no
 * automatic recovery path.
 *
 * The bug this was extracted for
 * ------------------------------
 * ``canRefund`` keyed everything on ``payout_status`` and returned
 * ``false`` for ``not_applicable``. Connect rows carry
 * ``not_applicable`` *correctly* — FC's manual payout process does not
 * cover them — so Refund was hidden on every Connect transaction, for
 * platform admins too. The backend docstring had already named the
 * trap: "inferring from it would refuse every Connect refund outright".
 * The question the gate needs answered is "has FC sent the creator
 * their share yet?", and for a Connect row only
 * ``connect_transfer_status`` knows.
 */

export interface RefundGateRow {
  /** Nullable on the wire for historical rows that predate the column. */
  payment_provider: string | null
  status: string
  gross_amount_cents: number
  refunded_amount_cents: number
  payout_status: string
  payout_model?: string | null
  connect?: { status: string } | null
}

/** Connect states where the creator's share has left Fresh Collective.
 *  Still refundable — by the creator-owner as well as an admin — but the
 *  refund carries a recovery advisory. */
const CONNECT_MONEY_MOVED = new Set(['sent', 'partially_reversed'])

/** Connect states where nothing has been sent, or it has all come back. */
const CONNECT_NOTHING_OUTSTANDING = new Set([
  'awaiting_payment', 'pending', 'failed', 'reversed',
])

export function isConnectRow(row: RefundGateRow): boolean {
  return row.payout_model === 'connect'
}

/**
 * Whether to offer the Refund action.
 *
 * Connect rows are gated on the transfer status; manual rows keep the
 * ``payout_status`` logic they have always had, unchanged.
 *
 * An unrecognised Connect status refuses rather than guesses, matching
 * the backend's final branch — a state this build has not heard of is
 * not grounds for offering to move money.
 */
export function canRefundRow(
  row: RefundGateRow, isPlatformOwner: boolean,
): boolean {
  if (row.payment_provider !== 'stripe') return false
  if (row.status !== 'succeeded' && row.status !== 'partially_refunded') return false
  if (row.gross_amount_cents - row.refunded_amount_cents <= 0) return false

  if (isConnectRow(row)) {
    const transfer = row.connect?.status ?? ''
    // Both branches allow, for creator-owner and admin alike. The
    // difference is the advisory, not the permission — see
    // ``refundAdvisory``. Whether this viewer is authorised at all is
    // decided before the row reaches here, and again by the backend.
    if (CONNECT_NOTHING_OUTSTANDING.has(transfer)) return true
    if (CONNECT_MONEY_MOVED.has(transfer)) return true
    return false
  }

  if (row.payout_status === 'paid' || row.payout_status === 'held') {
    return isPlatformOwner
  }
  if (row.payout_status === 'not_applicable') return false
  return true
}

export type RefundAdvisory = 'none' | 'manual_recovery' | 'connect_reversal'

/**
 * What the admin must acknowledge before refunding.
 *
 * Two different warnings, because two different things happen. For a
 * manual row Fresh Collective will not recover the creator's share at
 * all — it is a human follow-up. For a Connect row FC *does* attempt
 * the reversal automatically once the refund lands; the risk is
 * narrower, that Stripe refuses it because the creator's balance
 * cannot cover it. Showing the manual copy on a Connect refund would
 * be wrong in the more alarming direction, telling an admin no recovery
 * will be attempted when one will.
 */
export function refundAdvisory(row: RefundGateRow): RefundAdvisory {
  if (isConnectRow(row)) {
    return CONNECT_MONEY_MOVED.has(row.connect?.status ?? '')
      ? 'connect_reversal'
      : 'none'
  }
  return row.payout_status === 'paid' || row.payout_status === 'held'
    ? 'manual_recovery'
    : 'none'
}


export type ToastTone = 'success' | 'attention'

export interface RefundToast {
  text: string
  tone: ToastTone
}

export interface RefundResultLike {
  terminal_status?: string | null
  stripe_refund_id?: string | null
  message?: string | null
}

/**
 * What to tell the operator the instant a refund is submitted.
 *
 * The old message appended "creator has already been paid; manual
 * recovery required" whenever the backend returned a ``payout_advisory``
 * — and it returns the same advisory string for a manual payout and for
 * a Connect transfer, so a Connect refund announced manual recovery
 * before anything had even been attempted.
 *
 * For Connect that is wrong twice over. Fresh Collective *does* attempt
 * the reversal, automatically, moments later; and whether any manual
 * follow-up is needed is not knowable yet — it depends on whether the
 * connected account's balance covers the clawback. Manual-recovery
 * language belongs where that outcome is actually known: the
 * transaction's own status once ``connect_recovery_state`` lands on
 * ``required``, and the admin Today's Focus item that watches for it.
 *
 * The manual case is unchanged, because there the claim is true at the
 * moment it is made: nothing automatic will recover that money.
 */
export function refundToast(
  result: RefundResultLike,
  advisory: RefundAdvisory,
): RefundToast {
  const status = result.terminal_status
  let text: string
  if (status === 'webhook_confirmed') {
    text = `Refund confirmed${result.stripe_refund_id ? ` — ${result.stripe_refund_id}` : ''}.`
  } else if (status === 'accepted') {
    text = 'Refund initiated. The ledger updates when Stripe confirms, usually within seconds.'
  } else {
    text = result.message || 'Refund submitted.'
  }

  if (advisory === 'connect_reversal') {
    return {
      text:
        `${text} Fresh Collective will automatically attempt to recover the ` +
        `creator’s transfer.`,
      tone: 'success',
    }
  }

  if (advisory === 'manual_recovery') {
    return {
      text:
        `${text} The creator has already been paid — recovering their share ` +
        `is a manual follow-up.`,
      tone: 'attention',
    }
  }

  return { text, tone: 'success' }
}
