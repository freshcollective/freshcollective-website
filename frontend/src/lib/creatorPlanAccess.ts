import type { CreatorPlanOut, CreatorSubscriptionOut } from '@/types/platform'

/**
 * How a creator actually holds their plan — and what is truthful to say
 * about it.
 *
 * Why this exists
 * ---------------
 * `creator_plans.monthly_price_cents` is the plan's *retail* price. It
 * is not what every creator pays. An admin-assigned plan
 * (`creator_subscriptions.source='manual_grant'`) has no Stripe
 * subscription behind it at all, so quoting "$19 / month" to a
 * complimentary creator tells them they are being charged when nothing
 * will ever bill them.
 *
 * What the backend actually does (audited 2026-10-04, do not soften
 * this without re-checking)
 * ---------------------------
 *   * A manual grant writes `creator_subscriptions` with
 *     `source='manual_grant'`, `grant_reason`, `starts_at` and
 *     `ends_at`. It writes **no** `stripe_subscription_id` and no
 *     `stripe_customer_id`, so Stripe has nothing to invoice. There is
 *     no charge, now or at the end of the term.
 *   * **Nothing enforces `ends_at`.** `plan_guards.resolve_creator_plan`
 *     filters on `status` only, and the sole subscription cron
 *     (`creator_subscription_grace_reconcile.py`) sweeps
 *     `past_due → unpaid` on `grace_expires_at` — it never looks at
 *     `ends_at`. Every other reference to `ends_at` in the backend is a
 *     write or a display read.
 *   * Therefore a grant does **not** expire by itself. When `ends_at`
 *     passes, the creator keeps the plan until an admin extends or
 *     revokes it.
 *
 * That last point is why this module says "Granted until" rather than
 * "Active until", and why it never promises a cutoff or a future
 * charge. Saying "active until 4 Nov" would imply an automatic end the
 * platform does not perform; saying "then $19/month" would invent a
 * charge that cannot happen.
 *
 * `source` alone is not enough to pick the wording: it only separates
 * Stripe-billed from administratively-granted. `grant_reason='comp'`
 * is the one that means complimentary, so it gets the explicit
 * "Complimentary" label and the rest get a neutral "granted by Fresh
 * Collective".
 */

export type CreatorAccessKind =
  /** Stripe-billed subscription — the retail price is what they pay. */
  | 'paid'
  /** Admin-assigned, reason='comp'. Free, and described as such. */
  | 'complimentary'
  /** Admin-assigned for some other administrative reason. Also unbilled. */
  | 'granted'
  /** A genuinely free plan (Community) — free by design, not by grant. */
  | 'free'
  /** No subscription row resolved. */
  | 'none'

export interface CreatorAccessView {
  kind: CreatorAccessKind
  /**
   * What to show instead of the plan's retail monthly price, or null to
   * use the retail price as-is. Only non-null when the creator is not
   * actually being charged it.
   */
  priceOverride: string | null
  /** Short headline for the access arrangement, or null when the plain
   *  plan name already tells the truth. */
  label: string | null
  /** A factual sentence about the term. Never speculative. */
  termNote: string | null
  /** True when the creator pays nothing for this plan. */
  isUnbilled: boolean
}

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

/** `ends_at` in the past. Access continues regardless — see module note. */
function termHasPassed(iso: string | null | undefined, now: Date): boolean {
  if (!iso) return false
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return false
  return d.getTime() < now.getTime()
}

export function describeCreatorAccess(
  plan: CreatorPlanOut | null | undefined,
  subscription: CreatorSubscriptionOut | null | undefined,
  now: Date = new Date(),
): CreatorAccessView {
  const none: CreatorAccessView = {
    kind: 'none', priceOverride: null, label: null,
    termNote: null, isUnbilled: false,
  }
  if (!plan) return none

  // A $0 plan is free on its own terms (Community). Not a grant, and
  // nothing to explain.
  if (plan.monthly_price_cents === 0) {
    return {
      kind: 'free', priceOverride: null, label: null,
      termNote: null, isUnbilled: true,
    }
  }

  if (!subscription) return none

  if (subscription.source !== 'manual_grant') {
    // Stripe-billed. The retail price is the truth here.
    return {
      kind: 'paid', priceOverride: null, label: null,
      termNote: null, isUnbilled: false,
    }
  }

  const isComp = subscription.grant_reason === 'comp'
  const endsOn = formatDate(subscription.ends_at)
  const passed = termHasPassed(subscription.ends_at, now)

  // Never claims a future charge, and never claims the access will stop
  // on its own — neither is true of a manual grant.
  let termNote: string
  if (!endsOn) {
    termNote = 'Granted with no end date. This is not a paid subscription, so you will not be charged.'
  } else if (passed) {
    termNote = `Granted until ${endsOn}. Your access is still active.`
  } else {
    termNote = `Granted until ${endsOn}. This is not a paid subscription, so you will not be charged.`
  }

  return {
    kind: isComp ? 'complimentary' : 'granted',
    priceOverride: isComp ? 'Complimentary' : 'Provided by Fresh Collective',
    label: isComp
      ? 'Complimentary Creator access'
      : 'Creator access granted by Fresh Collective',
    termNote,
    isUnbilled: true,
  }
}
