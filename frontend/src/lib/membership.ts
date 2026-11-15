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
 * An amount as the member agreed to it, with the currency said out loud.
 *
 * The walkthrough found one amount written three ways — `$29/month`,
 * `$29 AUD / month` and (on Stripe's own page) `A$29.00`. The first is
 * the problem: at least five currencies use a bare `$`, so it tells a
 * member the digits and leaves them guessing the money.
 *
 * `en-US` with `currencyDisplay: 'symbol'` is what produces the
 * disambiguating forms — `A$29`, `NZ$29`, `£29`, `€29` — where the
 * `en-AU` locale collapses AUD, USD and NZD all to `$`. The locale is
 * a formatting choice, not a statement about the reader: it is picked
 * because it is the one that distinguishes the dollars.
 *
 * USD is the single case `en-US` still renders bare, naturally enough,
 * so it is named explicitly. Without that the ambiguity would simply
 * move: a Collective charging USD would show `$29` to a member who
 * has every reason to read it as Australian.
 *
 * Whole dollars carry no decimals, because `A$29/month` is what a
 * creator typed and `A$29.00/month` is not; an amount with cents
 * shows both.
 */
export function formatMoney(cents: number, currency: string): string {
  const amount = cents / 100
  const code = (currency || 'AUD').toUpperCase()
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: code,
    currencyDisplay: 'symbol',
    minimumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount)
  return code === 'USD' ? formatted.replace('$', 'US$') : formatted
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
  if (interval === ONE_TIME_INTERVAL) return `${money} once`
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


/**
 * Does the signed-in viewer belong to this Collective?
 *
 * The rule, as a function, because getting it wrong is what shipped
 * "Join collective" to a paying member for six months.
 *
 * The viewer's **own memberships** are the authority. The member
 * *directory* is not, and must never be: it is privacy-filtered and
 * returns nothing for learners whenever `show_member_directory` is
 * off, which is the default — so a member of a private-directory
 * Collective looked like a stranger to their own Collective.
 *
 * The directory is still consulted as a second yes, never as a no.
 * It reports creators and moderators faithfully, and an owner who
 * predates auto-membership can appear there without a membership
 * row. Either source saying "yes" is enough; only both staying
 * silent means not a member.
 */
export function recognisesMembership(options: {
  memberships: { space_slug: string }[]
  slug: string
  directoryMatch?: boolean
}): boolean {
  const { memberships, slug, directoryMatch = false } = options
  return memberships.some((m) => m.space_slug === slug) || directoryMatch
}

/**
 * Does this member still owe a subscription to keep their access?
 *
 * True only when all three hold: a transition is pending for them,
 * they may actually subscribe, and there is therefore something to
 * act on. False while the feature flag is off, because
 * `can_subscribe` is false then — an action that cannot be completed
 * should not be offered.
 */
export function owesConversion(state: MembershipState | null): boolean {
  if (!state) return false
  return state.transition.action_needed && state.actions.can_subscribe
}
