/**
 * Stage 5A.4a — membership recognition and money, as rules.
 *
 * Two defects the authenticated walkthrough found, pinned so they
 * cannot return:
 *
 *   1. A paying member was shown "Join collective", because
 *      membership was read from the privacy-filtered member
 *      *directory* rather than from the viewer's own memberships.
 *   2. One amount was written three ways — "$29/month", "$29 AUD /
 *      month" and "A$29.00" — the first of which tells a member the
 *      digits and leaves them guessing the currency.
 */

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  formatMoney, formatRecurring, offerPhrase, owesConversion,
  paidJoinAction, recognisesMembership, subscribeRefusalMessage,
} from './membership.ts'
import type { MembershipState } from '../types/platform.ts'

const m = (slug: string) => ({ space_slug: slug })

describe('recognisesMembership', () => {
  test('a member is recognised when the directory is hidden', () => {
    // The defect exactly: show_member_directory=false means the
    // directory returns nothing, so directoryMatch is false.
    assert.equal(
      recognisesMembership({
        memberships: [m('life-in-full-colour')],
        slug: 'life-in-full-colour',
        directoryMatch: false,
      }),
      true,
    )
  })

  test('a member is recognised when the directory is visible', () => {
    assert.equal(
      recognisesMembership({
        memberships: [m('life-in-full-colour')],
        slug: 'life-in-full-colour',
        directoryMatch: true,
      }),
      true,
    )
  })

  test('the directory alone is still a yes', () => {
    // An owner predating auto-membership has no membership row but
    // does appear in the directory. Either source is sufficient.
    assert.equal(
      recognisesMembership({
        memberships: [],
        slug: 'life-in-full-colour',
        directoryMatch: true,
      }),
      true,
    )
  })

  test('a non-member is not recognised', () => {
    assert.equal(
      recognisesMembership({
        memberships: [m('somewhere-else')],
        slug: 'life-in-full-colour',
        directoryMatch: false,
      }),
      false,
    )
  })

  test('a signed-out visitor has no memberships and is not recognised', () => {
    assert.equal(
      recognisesMembership({ memberships: [], slug: 'anything' }),
      false,
    )
  })

  test('another Collective’s membership does not count', () => {
    assert.equal(
      recognisesMembership({
        memberships: [m('a'), m('b')],
        slug: 'c',
        directoryMatch: false,
      }),
      false,
    )
  })
})

function state(over: Partial<MembershipState> = {}): MembershipState {
  return {
    space: { id: 's', slug: 'c', name: 'C' },
    is_member: true,
    membership_status: 'active',
    is_owner: false,
    offer: {
      pricing_type: 'paid_monthly', amount_cents: 2900, currency: 'AUD',
      is_paid: true, subscribable: true,
    },
    transition: {
      effective_at: null, effective_on: null, has_passed: false,
      action_needed: false,
    },
    subscription: null,
    actions: {
      can_subscribe: true, subscribe_refusal: null,
      can_cancel_renewal: false, can_resume: false,
      can_update_payment_method: false, can_continue_checkout: false,
    },
    ...over,
  } as MembershipState
}

describe('owesConversion', () => {
  test('a member facing a transition who may subscribe owes one', () => {
    assert.equal(owesConversion(state({
      transition: { effective_at: '2027-01-01T00:00:00', effective_on: '2027-01-01', has_passed: false, action_needed: true },
    })), true)
  })

  test('nothing is owed when no transition is pending', () => {
    assert.equal(owesConversion(state()), false)
  })

  test('nothing is offered while the feature flag is off', () => {
    // can_subscribe is false when billing is disabled, so the action
    // must not appear — offering a door that refuses is worse than
    // offering none.
    assert.equal(owesConversion(state({
      transition: { effective_at: '2027-01-01T00:00:00', effective_on: '2027-01-01', has_passed: false, action_needed: true },
      actions: { ...state().actions, can_subscribe: false, subscribe_refusal: 'membership_billing_unavailable' },
    })), false)
  })

  test('an absent state owes nothing', () => {
    assert.equal(owesConversion(null), false)
  })
})

describe('formatMoney', () => {
  test('AUD names itself rather than using a bare dollar sign', () => {
    assert.equal(formatMoney(2900, 'AUD'), 'A$29')
  })

  test('whole dollars carry no decimals', () => {
    assert.equal(formatMoney(29000, 'AUD'), 'A$290')
  })

  test('an amount with cents shows both', () => {
    assert.equal(formatMoney(2950, 'AUD'), 'A$29.50')
  })

  test('USD is distinguished too, or the ambiguity just moves', () => {
    assert.equal(formatMoney(4900, 'USD'), 'US$49')
  })

  test('a non-dollar currency keeps its own symbol', () => {
    assert.equal(formatMoney(2900, 'GBP'), '£29')
  })

  test('NZD is not mistaken for AUD', () => {
    assert.equal(formatMoney(2900, 'NZD'), 'NZ$29')
  })

  test('a missing currency falls back to AUD rather than throwing', () => {
    assert.equal(formatMoney(2900, ''), 'A$29')
  })
})

describe('formatRecurring', () => {
  test('monthly', () => {
    assert.equal(formatRecurring(2900, 'AUD', 'month'), 'A$29/month')
  })

  test('annual', () => {
    assert.equal(formatRecurring(29000, 'AUD', 'year'), 'A$290/year')
  })

  test('one-time says once, never per-anything', () => {
    assert.equal(formatRecurring(19900, 'AUD', 'one_time'), 'A$199 once')
  })

  test('a multi-interval agreement pluralises', () => {
    assert.equal(formatRecurring(2900, 'AUD', 'month', 3), 'A$29/3 months')
  })
})

describe('offerPhrase', () => {
  test('quotes the Collective’s current list price', () => {
    assert.equal(offerPhrase(state()), 'A$29/month')
  })

  test('an annual offer is quoted per year', () => {
    assert.equal(offerPhrase(state({
      offer: { pricing_type: 'paid_annual', amount_cents: 29000, currency: 'AUD', is_paid: true, subscribable: true },
    })), 'A$290/year')
  })

  test('a one-off joining fee is quoted once', () => {
    assert.equal(offerPhrase(state({
      offer: { pricing_type: 'paid_one_time', amount_cents: 19900, currency: 'AUD', is_paid: true, subscribable: true },
    })), 'A$199 once')
  })

  test('a free Collective offers nothing to quote', () => {
    assert.equal(offerPhrase(state({
      offer: { pricing_type: 'free', amount_cents: null, currency: 'AUD', is_paid: false, subscribable: false },
    })), null)
  })
})

describe('an agreement is quoted on its own terms, not the list price', () => {
  test('a member who joined at A$29 still reads A$29 after a reprice', () => {
    // The agreement's frozen amount and the Collective's current
    // offer are different numbers and must stay that way.
    const s = state({
      offer: { pricing_type: 'paid_monthly', amount_cents: 3900, currency: 'AUD', is_paid: true, subscribable: true },
      subscription: {
        id: 'cm', status: 'active', amount_cents: 2900, currency: 'AUD',
        interval: 'month', interval_count: 1, is_one_time: false,
        current_period_end: null, cancel_at_period_end: false,
        renews_at: null, access_until: null, grace_expires_at: null,
        started_at: null, ended_at: null,
      },
    })
    assert.equal(
      formatRecurring(
        s.subscription!.amount_cents, s.subscription!.currency,
        s.subscription!.interval, s.subscription!.interval_count,
      ),
      'A$29/month',
    )
    assert.equal(offerPhrase(s), 'A$39/month')
  })
})

describe('subscribeRefusalMessage', () => {
  test('the flag being off is said plainly', () => {
    assert.match(
      subscribeRefusalMessage('membership_billing_unavailable') ?? '',
      /isn.t available yet/,
    )
  })

  test('no refusal is no message', () => {
    assert.equal(subscribeRefusalMessage(null), null)
  })
})


// ===========================================================================
// Stage 5A.4b — the paid Collective CTA
// ===========================================================================

/**
 * The defect, pinned twice over.
 *
 * Production showed **"Join collective"** on a Collective charging
 * A$5.99/month. The control was the membership checkout all along —
 * the right action wearing the free one's words — and it was rendered
 * whether or not billing was switched on, so with the flag off it was
 * a door that refuses.
 */
function paid(over: Partial<MembershipState['actions']> = {},
              offer?: Partial<MembershipState['offer']>): MembershipState {
  return state({
    is_member: false,
    offer: {
      pricing_type: 'paid_monthly', amount_cents: 599, currency: 'AUD',
      is_paid: true, subscribable: true, ...offer,
    },
    actions: { ...state().actions, can_subscribe: true, ...over },
  } as Partial<MembershipState>)
}

describe('paidJoinAction — what the button says', () => {
  test('the reported case: the price is on the button, not "Join collective"', () => {
    const a = paidJoinAction(paid())
    assert.equal(a.kind, 'subscribe')
    assert.equal(a.kind === 'subscribe' && a.label, 'Subscribe — A$5.99/month')
    assert.notEqual(a.kind === 'subscribe' && a.label, 'Join collective')
  })

  test('annual membership says per year', () => {
    const a = paidJoinAction(paid({}, {
      pricing_type: 'paid_annual', amount_cents: 999,
    }))
    assert.equal(a.kind === 'subscribe' && a.label, 'Subscribe — A$9.99/year')
  })

  test('a one-time membership says once, never per-anything', () => {
    const a = paidJoinAction(paid({}, {
      pricing_type: 'paid_one_time', amount_cents: 799,
    }))
    assert.equal(a.kind === 'subscribe' && a.label, 'Subscribe — A$7.99 once')
  })

  test('an offer with no amount still offers a usable button', () => {
    const a = paidJoinAction(paid({}, { amount_cents: null, is_paid: false }))
    assert.equal(a.kind === 'subscribe' && a.label, 'Subscribe')
  })

  test('the label never hard-codes an amount', () => {
    // A$5.99 is this test Collective's price, not the product's.
    const a = paidJoinAction(paid({}, { amount_cents: 12345 }))
    assert.equal(a.kind === 'subscribe' && a.label, 'Subscribe — A$123.45/month')
  })
})

describe('paidJoinAction — whether there is a button at all', () => {
  test('can_subscribe true is what opens the door', () => {
    assert.equal(paidJoinAction(paid({ can_subscribe: true })).kind, 'subscribe')
  })

  test('billing off offers no action, and says why', () => {
    const a = paidJoinAction(paid({
      can_subscribe: false, subscribe_refusal: 'membership_billing_unavailable',
    }))
    assert.equal(a.kind, 'unavailable')
    assert.match(a.kind === 'unavailable' ? a.message : '', /isn.t available yet/)
  })

  test('each refusal gets its own sentence rather than a button', () => {
    for (const [code, pattern] of [
      ['already_subscribed', /already have a membership/i],
      ['membership_own_collective', /your collective/i],
      ['membership_auto_managed', /managed by Fresh Collective/i],
      ['membership_not_available_to_you', /cannot be purchased/i],
    ] as const) {
      const a = paidJoinAction(paid({ can_subscribe: false, subscribe_refusal: code }))
      assert.equal(a.kind, 'unavailable', code)
      assert.match(a.kind === 'unavailable' ? a.message : '', pattern, code)
    }
  })

  test('a removed or banned member is refused without a code leaking why', () => {
    const a = paidJoinAction(paid({
      can_subscribe: false, subscribe_refusal: 'membership_not_eligible',
    }))
    assert.equal(a.kind, 'unavailable')
    assert.match(a.kind === 'unavailable' ? a.message : '', /isn.t available to you/i)
  })

  test('unknown eligibility is not a reason to offer checkout', () => {
    // The state fetch failed. Guessing "yes" is the failure this
    // function exists to stop.
    const a = paidJoinAction(null)
    assert.equal(a.kind, 'unavailable')
    assert.ok((a.kind === 'unavailable' ? a.message : '').length > 0)
  })

  test('can_subscribe is required to be exactly true', () => {
    for (const v of [undefined, null, 0, '', 'true'] as unknown[]) {
      const s = paid()
      ;(s.actions as Record<string, unknown>).can_subscribe = v
      assert.equal(paidJoinAction(s).kind, 'unavailable', String(v))
    }
  })
})

/**
 * Branch order in the CTA, asserted against the source.
 *
 * These are ordering guarantees no unit test of a pure function can
 * make, and getting them wrong is how a paid Collective would start
 * offering free membership. Matched on code rather than prose — a
 * comment mentioning "isPublic" must not satisfy them.
 */
describe('SpaceAboutCTA branch order', () => {
  const HERE = dirname(fileURLToPath(import.meta.url))
  const cta = readFileSync(
    join(HERE, '..', 'app', 'spaces', '[slug]', 'about', 'SpaceAboutCTA.tsx'),
    'utf8',
  )
  const at = (needle: string) => {
    const i = cta.indexOf(needle)
    assert.notEqual(i, -1, `not found in source: ${needle}`)
    return i
  }

  test('a purchase_required Collective is handled before paid pricing', () => {
    assert.ok(at("joinPolicy === 'purchase_required'") < at('isPaidPricingType(pricingType)'))
  })

  test('paid pricing is handled before the public free-join branch', () => {
    // If this inverts, a public paid Collective offers free joining.
    assert.ok(at('isPaidPricingType(pricingType)') < at('if (isPublic) {'))
  })

  test('the signed-out branch comes before paid pricing', () => {
    assert.ok(at('if (!isLoggedIn) {') < at('isPaidPricingType(pricingType)'))
  })

  test('an existing member is handled before any join door', () => {
    assert.ok(at('if (isMember) {') < at('isPaidPricingType(pricingType)'))
  })

  test('the paid branch asks paidJoinAction rather than deciding itself', () => {
    assert.match(cta, /const action = paidJoinAction\(membershipState\)/)
  })

  test('the free-join label is gone from the paid branch', () => {
    // The whole defect: SubscribeButton carrying the free door's words.
    assert.doesNotMatch(cta, /label="Join collective"/)
  })

  test('checkout still goes through SubscribeButton', () => {
    assert.match(cta, /<SubscribeButton\b/)
  })
})
