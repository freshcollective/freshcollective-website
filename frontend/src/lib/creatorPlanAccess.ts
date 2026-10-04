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
 *   * A finite grant **does** now expire.
 *     `services/creator_grant_expiry.py` cancels the grant row once
 *     `ends_at` has passed, and `resolve_creator_plan`'s
 *     cheapest-active-plan fallback returns the creator to Community.
 *     Only `grant_reason` 'comp' and 'temporary' are eligible, and only
 *     on purchasable tiers — Founding Creator, Organisation and
 *     indefinite grants (`ends_at IS NULL`) are excluded by design.
 *   * Expiry is scheduled, so a grant whose date has just passed can
 *     briefly still be active. That state gets no special copy: it is
 *     transient, and the reconciler leaves a row alone entirely when
 *     downgrading would be unsafe (more Collectives than Community
 *     allows, or live paid content), for an admin to resolve.
 *
 * So "Active until" is accurate for a future end date. What this
 * module must still never say is "then $19/month": expiry creates no
 * Stripe subscription and charges nobody — the fallback is to the free
 * Community plan, never to a paid one.
 *
 * `source` alone is not enough to pick the wording: it only separates
 * Stripe-billed from administratively-granted. `grant_reason='comp'`
 * is the one that means complimentary, so it gets the explicit
 * "Complimentary" label and the rest get a neutral "granted by Fresh
 * Collective".
 */

/**
 * Where a finite complimentary grant sits in its lifecycle. Mirrors
 * ``services/creator_grant_expiry.classify_grant`` — 14 days of renewal
 * window before ``ends_at``, then 7 days of grace after it.
 */
export type ComplimentaryPhase =
  /** More than 14 days left. No urgency. */
  | 'active'
  /** Final 14 days — invite them to continue. */
  | 'renewal'
  /** Term ended; Creator access continues for 7 more days. */
  | 'grace'
  /** Not a finite complimentary grant. */
  | 'none'

export const RENEWAL_WINDOW_DAYS = 14
export const GRACE_PERIOD_DAYS = 7

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
  /** Lifecycle phase of a finite complimentary grant. */
  phase: ComplimentaryPhase
  /** End of the 7-day grace window, when in or approaching grace. */
  graceEndsOn: string | null
  /** The grant's own end date, formatted. */
  endsOn: string | null
}

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function describeCreatorAccess(
  plan: CreatorPlanOut | null | undefined,
  subscription: CreatorSubscriptionOut | null | undefined,
  now: Date = new Date(),
): CreatorAccessView {
  const none: CreatorAccessView = {
    kind: 'none', priceOverride: null, label: null,
    termNote: null, isUnbilled: false,
    phase: 'none', graceEndsOn: null, endsOn: null,
  }
  if (!plan) return none

  // A $0 plan is free on its own terms (Community). Not a grant, and
  // nothing to explain.
  if (plan.monthly_price_cents === 0) {
    return {
      kind: 'free', priceOverride: null, label: null,
      termNote: null, isUnbilled: true,
      phase: 'none', graceEndsOn: null, endsOn: null,
    }
  }

  if (!subscription) return none

  if (subscription.source !== 'manual_grant') {
    // Stripe-billed. The retail price is the truth here.
    return {
      kind: 'paid', priceOverride: null, label: null,
      termNote: null, isUnbilled: false,
      phase: 'none', graceEndsOn: null, endsOn: null,
    }
  }

  const isComp = subscription.grant_reason === 'comp'
  const endsOn = formatDate(subscription.ends_at)

  // Lifecycle phase. Only a finite grant has one — an indefinite grant
  // never approaches an end date.
  const endsAt = subscription.ends_at ? new Date(subscription.ends_at) : null
  const endsAtValid = endsAt && !Number.isNaN(endsAt.getTime()) ? endsAt : null
  let phase: ComplimentaryPhase = 'none'
  let graceEnd: Date | null = null
  if (endsAtValid) {
    graceEnd = new Date(endsAtValid.getTime() + GRACE_PERIOD_DAYS * 86400000)
    const renewalOpens = new Date(
      endsAtValid.getTime() - RENEWAL_WINDOW_DAYS * 86400000,
    )
    if (now < renewalOpens) phase = 'active'
    else if (now < endsAtValid) phase = 'renewal'
    else if (now < graceEnd) phase = 'grace'
    else phase = 'grace'   // past grace: the reconciler has not run yet
  }
  const graceEndsOn = graceEnd ? formatDate(graceEnd.toISOString()) : null

  // States when the access ends, and never implies a charge follows —
  // none does. Continuing is always an explicit purchase; not
  // continuing returns them to the free Community plan.
  let termNote: string
  if (!endsOn) {
    termNote = 'No end date. This is not a paid subscription, so you will not be charged.'
  } else if (phase === 'grace') {
    termNote = graceEndsOn
      ? `Your complimentary access ended on ${endsOn}. You have until ${graceEndsOn} to continue on Creator before your account moves to Community.`
      : `Your complimentary access ended on ${endsOn}.`
  } else if (phase === 'renewal') {
    termNote = `Your complimentary Creator access ends on ${endsOn}.`
  } else {
    termNote = `Active until ${endsOn}. This is not a paid subscription, so you will not be charged.`
  }

  return {
    kind: isComp ? 'complimentary' : 'granted',
    priceOverride: isComp ? 'Complimentary' : 'Provided by Fresh Collective',
    label: isComp
      ? (phase === 'grace'
        ? 'Your complimentary Creator access has ended'
        : 'Complimentary Creator access')
      : 'Creator access granted by Fresh Collective',
    termNote,
    isUnbilled: true,
    phase,
    graceEndsOn,
    endsOn,
  }
}
