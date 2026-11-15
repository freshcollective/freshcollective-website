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

import {
  formatMoney, formatRecurring, offerPhrase, owesConversion,
  recognisesMembership, subscribeRefusalMessage,
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
