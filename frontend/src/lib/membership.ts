/**
 * One place that knows how to talk about a Collective membership.
 *
 * Four surfaces describe the same agreement — the Collective's About
 * page, the post-Stripe return, Account Settings, and a lapsed
 * member's prompt to come back. They must not word the same facts
 * differently, and they must not each invent their own currency
 * formatting, so the phrasing and the maths live here.
 */

import type { MembershipState } from '@/types/platform'

/**
 * An amount as the member agreed to it.
 *
 * `Intl` with the real currency code rather than a bare `$`: an
 * agreement carries its own currency, and A$29 and US$29 are not the
 * same promise. Whole dollars when the cents are zero, because
 * "A$29/month" is what a creator wrote and "A$29.00/month" is not.
 */
export function formatMoney(cents: number, currency: string): string {
  const amount = cents / 100
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency || 'AUD',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount)
}

/**
 * "A$29/month", "A$290/year", or "A$199 paid once".
 *
 * The commitment travels with the price deliberately. A bare "A$199"
 * beside a membership reads as a subscription to anyone who has seen
 * one, and the whole point of the one-time arrangement is that it is
 * not.
 */
export function formatRecurring(
  cents: number, currency: string, interval: string, intervalCount = 1,
): string {
  const money = formatMoney(cents, currency)
  if (interval === ONE_TIME_INTERVAL) return `${money} paid once`
  const every = intervalCount > 1 ? `${intervalCount} ${interval}s` : interval
  return `${money}/${every}`
}

/** Matches the backend's ``ONE_TIME_INTERVAL``. */
export const ONE_TIME_INTERVAL = 'one_time'

/** A date a person can read, in their own locale's long form. */
export function formatDay(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString('en-AU', {
    day: 'numeric', month: 'long', year: 'numeric',
  })
}

/**
 * What the member is being offered, if anything, in one phrase.
 *
 * Null when there is nothing to offer — which is a complete answer
 * and the reason a caller should render nothing rather than an empty
 * price.
 */
export function offerPhrase(state: MembershipState): string | null {
  const { offer } = state
  if (!offer.is_paid || !offer.amount_cents) return null
  if (offer.pricing_type === 'paid_one_time') {
    return formatRecurring(
      offer.amount_cents, offer.currency, ONE_TIME_INTERVAL,
    )
  }
  const interval = offer.pricing_type === 'paid_annual' ? 'year' : 'month'
  return formatRecurring(offer.amount_cents, offer.currency, interval)
}

/**
 * Why a member cannot subscribe, said in words rather than a code.
 *
 * Only the refusals a member can actually encounter and do something
 * about are translated. Anything else falls through to a neutral
 * sentence rather than leaking a backend code into the page.
 */
export function subscribeRefusalMessage(code: string | null): string | null {
  switch (code) {
    case null:
      return null
    case 'membership_billing_unavailable':
      return 'Paid membership isn’t available yet.'
    case 'membership_not_paid':
      return 'This collective doesn’t charge for membership.'
    case 'already_subscribed':
      return 'You already have a membership subscription here.'
    case 'membership_own_collective':
      return 'This is your collective — your membership of it never lapses.'
    case 'membership_auto_managed':
      return 'Membership of this collective is managed by Fresh Collective.'
    case 'membership_not_available_to_you':
      return 'Membership of this collective cannot be purchased right now. '
        + 'Please contact the collective’s creator.'
    default:
      return 'Membership isn’t available to you right now.'
  }
}
