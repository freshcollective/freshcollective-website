/**
 * World Management's view of whether a creator's sales may be switched
 * over to Stripe Connect, and what is stopping it.
 *
 * Pure, so the whole decision table is unit-testable under Node's test
 * runner without importing JSX. The card renders what this returns and
 * decides nothing itself.
 *
 * What this surface is, and what it is not
 * ----------------------------------------
 * ``connect_payouts_enabled_at`` has exactly one writer in the whole
 * system, and it is the admin endpoint this card calls. Onboarding
 * finishing does not set it, a webhook reporting a capability active does
 * not set it, and a creator acknowledging the fee model does not set it.
 * Stripe saying an account is ready is an *input* to the decision, never
 * the decision — so nothing here may act on its own, and the readiness
 * fetch must never trigger a write.
 *
 * The switch is also forward-only. Purchases and plans already created
 * snapshotted their payout model at creation and keep it, so enabling
 * changes where *future* sales go and disabling stops *future* sales from
 * going there. Neither touches a transfer already owed. An admin reading
 * this card needs to know that before they press anything, so both
 * confirmation lines say it.
 */

import type { AdminConnectReadiness } from '@/types/platform'

export type RoutingTone = 'live' | 'ready' | 'blocked'

export type RoutingAction = 'enable' | 'disable' | 'none'

export interface RoutingFact {
  label: string
  value: string
}

export interface RoutingView {
  badge: string
  tone: RoutingTone
  /** One sentence on where this creator's future sales go right now. */
  summary: string
  /** Plain-English blockers. Empty when routing is live or ready. */
  blockers: string[]
  action: RoutingAction
  actionLabel: string | null
  /** Shown before the action commits. Both mention the forward-only rule. */
  confirmPrompt: string | null
  facts: RoutingFact[]
}

/**
 * Blocker codes as the backend emits them, in
 * ``connect_routing_enablement``. Kept as a literal map rather than a
 * lookup with a generated default so a code the backend adds later shows
 * up as the explicit fallback below rather than as an empty bullet.
 */
export function explainBlocker(code: string, stripeMode: string): string {
  switch (code) {
    case 'no_account_for_current_mode':
      return (
        `This creator has no ${stripeMode}-mode Stripe account. They need to ` +
        'connect Stripe from their own Creator Studio first — it cannot be ' +
        'done for them.'
      )
    case 'no_stripe_account_id':
      return (
        'Their Stripe account has not been created yet. They have started ' +
        'the process but Stripe has not issued an account.'
      )
    case 'payouts_status_not_active':
      return (
        'Stripe has not activated payouts on their account. Until it does, ' +
        'money transferred to them could not reach their bank.'
      )
    case 'payouts_not_enabled':
      return 'Payouts are not enabled on their Stripe account.'
    case 'fee_disclosure_not_acknowledged':
      return (
        'They have not acknowledged the fee model. Connect changes what they ' +
        'receive, so they must see that before it applies. Only they can do ' +
        'this, from their own Creator Studio.'
      )
    default:
      return `Stripe Connect routing is blocked (${code}).`
  }
}

/** "2 October 2026 at 9:14 am". Empty string for anything unparseable. */
export function formatEnabledAt(iso: string | null): string {
  if (!iso) return ''
  const parsed = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleString('en-AU', {
    day: 'numeric', month: 'long', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

function titleCase(value: string): string {
  const spaced = value.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function facts(readiness: AdminConnectReadiness): RoutingFact[] {
  const rows: RoutingFact[] = [
    {
      label: 'Stripe account',
      value: readiness.has_stripe_account
        ? `Connected (${readiness.stripe_mode} mode)`
        : 'None',
    },
    {
      label: 'Onboarding',
      value: readiness.onboarding_state
        ? titleCase(readiness.onboarding_state)
        : 'Not started',
    },
    {
      label: 'Payouts',
      value: readiness.payouts_status
        ? `${titleCase(readiness.payouts_status)}${readiness.payouts_enabled ? '' : ' — not enabled'}`
        : 'Unknown',
    },
    {
      label: 'Fee acknowledgement',
      value: readiness.fee_disclosure_acknowledged
        ? readiness.fee_disclosure_version
          ? `Acknowledged (${readiness.fee_disclosure_version})`
          : 'Acknowledged'
        : 'Not acknowledged',
    },
  ]
  return rows
}

const FORWARD_ONLY =
  'Purchases and payment plans already created keep the payout model they ' +
  'were created with, so nothing in flight changes path.'

/**
 * Three states, and the card shows exactly one of them.
 *
 * Routing already on wins over readiness: a creator whose sales are live
 * through Connect but whose account has since picked up a blocker still
 * needs the Disable control, and hiding it behind "not ready" would leave
 * an admin unable to stop the thing that is actually running.
 */
export function describeRouting(readiness: AdminConnectReadiness): RoutingView {
  const shared = { facts: facts(readiness) }

  if (readiness.routing_enabled_at) {
    const when = formatEnabledAt(readiness.routing_enabled_at)
    return {
      ...shared,
      badge: 'Routing live',
      tone: 'live',
      summary: when
        ? `Future sales have routed through Connect since ${when}.`
        : 'Future sales route through this creator’s Stripe account.',
      blockers: [],
      action: 'disable',
      actionLabel: 'Disable Connect routing',
      confirmPrompt:
        'Stop routing this creator’s future sales through Connect? ' +
        FORWARD_ONLY +
        ' A transfer already owed is still owed.',
    }
  }

  if (readiness.ready_to_enable) {
    return {
      ...shared,
      badge: 'Ready to enable',
      tone: 'ready',
      summary:
        'Every condition holds. Their sales still reach them through the ' +
        'manual payout process until routing is enabled here.',
      blockers: [],
      action: 'enable',
      actionLabel: 'Enable Connect routing',
      confirmPrompt:
        'Route this creator’s future sales through Connect? Their share of ' +
        'each new sale will be transferred to their Stripe account ' +
        'automatically. ' + FORWARD_ONLY,
    }
  }

  return {
    ...shared,
    badge: 'Not ready',
    tone: 'blocked',
    summary:
      'Their sales reach them through the manual payout process. Routing ' +
      'cannot be enabled until the following are resolved.',
    blockers: readiness.blockers.map((b) => explainBlocker(b, readiness.stripe_mode)),
    action: 'none',
    actionLabel: null,
    confirmPrompt: null,
  }
}

/**
 * The message worth showing from a failed enable/disable.
 *
 * The 409 carries ``detail: {reason, message}`` — the message is already
 * written for a person, so it is preferred over anything composed here.
 * Everything else degrades to something an admin can act on rather than
 * to ``[object Object]``, which is what naive rendering of that detail
 * shape produces.
 */
export function errorMessageFrom(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail

  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message.trim()
    const reason = (detail as { reason?: unknown }).reason
    if (typeof reason === 'string' && reason.trim()) {
      return `Stripe Connect routing was refused (${reason.trim()}).`
    }
  }

  if (typeof detail === 'string' && detail.trim()) return detail.trim()

  if (status === 409) {
    return 'Conditions changed before this could be applied. Refresh and try again.'
  }
  if (status === 403) {
    return 'You do not have permission to change Connect routing.'
  }
  if (status === 404) {
    return 'This creator could not be found.'
  }
  return `Could not change Connect routing (HTTP ${status}).`
}
