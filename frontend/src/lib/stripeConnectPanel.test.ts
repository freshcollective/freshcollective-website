/**
 * The Stripe Connect panel's state machine and copy.
 *
 * The state names and field shapes here mirror the backend's
 * ``ConnectStatusResponse`` exactly, so a backend rename shows up as a
 * failure here rather than as a creator seeing the fallback copy.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import
import { describeConnect, feeDisclosure, payoutScheduleSentence } from './stripeConnectPanel.ts'

type State =
  | 'not_started' | 'onboarding' | 'verifying' | 'action_required'
  | 'transfers_only' | 'ready' | 'restricted' | 'unsupported' | 'closed'

const status = (state: State, overrides: Record<string, unknown> = {}) => ({
  connected: state !== 'not_started',
  state,
  stripe_mode: 'test',
  stripe_account_id: state === 'not_started' ? null : 'acct_123',
  transfers_status: null,
  transfers_status_codes: [],
  payouts_status: null,
  payouts_status_codes: [],
  transfers_enabled: false,
  payouts_enabled: false,
  details_submitted: false,
  requirements: [],
  requirements_deadline: null,
  action_required: false,
  external_account_count: 0,
  payout_interval: null,
  payout_delay_days: null,
  connect_routing_enabled: false,
  last_synced_at: null,
  last_sync_source: null,
  last_error_message: null,
  ...overrides,
})

const ALL_STATES: State[] = [
  'not_started', 'onboarding', 'verifying', 'action_required',
  'transfers_only', 'ready', 'restricted', 'unsupported', 'closed',
]

const requirement = (awaiting: string) => ({
  description: 'identity.individual.address.line1',
  awaiting_action_from: awaiting,
  restricts_capabilities: ['stripe_balance.stripe_transfers'],
  errors: [],
})

describe('every backend state renders', () => {
  test('all nine produce a badge, headline and body', () => {
    for (const state of ALL_STATES) {
      const view = describeConnect(status(state))
      assert.ok(view.badge.length > 0, `${state} badge`)
      assert.ok(view.headline.length > 0, `${state} headline`)
      assert.ok(view.body.length > 0, `${state} body`)
    }
  })

  test('an unknown state falls back to the cautious copy, not a reassuring one', () => {
    // A build that meets a state it does not know must not imply payouts
    // are fine.
    const view = describeConnect(status('some_future_state' as State))
    assert.equal(view.badge, 'Needs attention')
    assert.equal(view.action, 'none')
    assert.notEqual(view.tone, 'good')
  })
})

describe('labels and calls to action', () => {
  test('not connected offers Connect Stripe', () => {
    const view = describeConnect(status('not_started'))
    assert.equal(view.badge, 'Not connected')
    assert.equal(view.action, 'connect')
    assert.equal(view.actionLabel, 'Connect Stripe')
    assert.equal(view.showRefresh, false)
  })

  test('onboarding offers Continue setup', () => {
    const view = describeConnect(status('onboarding'))
    assert.equal(view.action, 'continue')
    assert.equal(view.actionLabel, 'Continue setup')
  })

  test('action required explains Stripe needs more and offers Continue setup', () => {
    const view = describeConnect(status('action_required', {
      details_submitted: true,
      requirements: [requirement('user')],
      action_required: true,
    }))
    assert.equal(view.action, 'continue')
    assert.equal(view.actionLabel, 'Continue setup')
    assert.match(view.body, /Stripe has asked for/)
    assert.equal(view.outstandingCount, 1)
  })

  test('action required counts only what the creator must do', () => {
    const view = describeConnect(status('action_required', {
      details_submitted: true,
      requirements: [requirement('user'), requirement('stripe'), requirement('user')],
    }))
    assert.equal(view.outstandingCount, 2)
    assert.match(view.body, /2 more details/)
  })

  test('verifying explains Stripe is reviewing, offers no setup CTA, allows refresh', () => {
    const view = describeConnect(status('verifying', {
      requirements: [requirement('stripe')],
    }))
    assert.match(view.headline, /reviewing/i)
    assert.match(view.body, /Nothing is needed from you/)
    assert.equal(view.action, 'none')
    assert.equal(view.showRefresh, true)
  })

  test('verifying never uses connected language', () => {
    const view = describeConnect(status('verifying'))
    const text = `${view.badge} ${view.headline} ${view.body}`.toLowerCase()
    assert.ok(!text.includes('connected'), text)
    assert.ok(!text.includes('ready to pay'), text)
    assert.notEqual(view.tone, 'good')
  })

  test('transfers_only explains funds can arrive but not leave, and sends them back to Stripe', () => {
    const view = describeConnect(status('transfers_only', {
      transfers_status: 'active', transfers_enabled: true,
      payouts_status: 'restricted', external_account_count: 0,
    }))
    assert.match(view.body, /can’t pay them out yet/)
    assert.match(view.body, /bank account/)
    assert.equal(view.action, 'continue')
    assert.equal(view.actionLabel, 'Add bank details')
  })

  test('restricted explains Stripe must resolve it, with no self-serve CTA', () => {
    const view = describeConnect(status('restricted'))
    assert.match(view.body, /isn’t something you can resolve/)
    assert.equal(view.action, 'none')
  })

  test('unsupported states payouts are unavailable and offers no retry', () => {
    const view = describeConnect(status('unsupported'))
    assert.match(view.headline, /aren’t available/)
    assert.equal(view.action, 'none')
    assert.equal(view.showRefresh, false)
    assert.equal(view.tone, 'stopped')
  })

  test('closed states the account is closed and cannot receive payouts', () => {
    const view = describeConnect(status('closed'))
    assert.match(view.headline, /closed/i)
    assert.match(view.body, /can’t receive payouts/)
    assert.equal(view.action, 'none')
    assert.equal(view.showRefresh, false)
  })
})

describe('ready does not overclaim', () => {
  const readyStatus = (overrides = {}) => status('ready', {
    transfers_status: 'active', transfers_enabled: true,
    payouts_status: 'active', payouts_enabled: true,
    details_submitted: true, external_account_count: 1,
    payout_interval: 'daily', payout_delay_days: 2,
    ...overrides,
  })

  test('shows connected and the payout schedule', () => {
    const view = describeConnect(readyStatus())
    assert.equal(view.badge, 'Connected')
    assert.equal(view.tone, 'good')
    assert.match(view.scheduleNote ?? '', /every day/)
    assert.match(view.scheduleNote ?? '', /2 days/)
  })

  test('with routing off, it says earnings still come the existing way', () => {
    // The whole point of the distinction: Stripe being ready is not FC
    // paying them this way.
    const view = describeConnect(readyStatus({ connect_routing_enabled: false }))
    assert.match(view.routingNote ?? '', /existing payout process/)
    assert.ok(!/sent to this Stripe account automatically/.test(view.routingNote ?? ''))
  })

  test('with routing off, nothing claims automatic FC payouts are live', () => {
    const view = describeConnect(readyStatus({ connect_routing_enabled: false }))
    const text = `${view.headline} ${view.body} ${view.routingNote}`
    assert.ok(!/automatically/.test(`${view.headline} ${view.body}`), text)
  })

  test('with routing on, it says the share is sent automatically', () => {
    const view = describeConnect(readyStatus({ connect_routing_enabled: true }))
    assert.match(view.routingNote ?? '', /sent to this Stripe account automatically/)
  })

  test('every non-terminal state carries a routing note', () => {
    for (const state of ALL_STATES) {
      const view = describeConnect(status(state))
      assert.ok(view.routingNote, `${state} should say where money goes`)
    }
  })
})

describe('payout schedule sentence', () => {
  test('daily with a two-day delay', () => {
    assert.match(payoutScheduleSentence('daily', 2) ?? '', /every day, about 2 days/)
  })

  test('weekly and monthly read naturally', () => {
    assert.match(payoutScheduleSentence('weekly', 2) ?? '', /once a week/)
    assert.match(payoutScheduleSentence('monthly', 5) ?? '', /once a month/)
  })

  test('singular day is not pluralised', () => {
    assert.match(payoutScheduleSentence('daily', 1) ?? '', /about 1 day after/)
  })

  test('no delay omits the delay clause', () => {
    const s = payoutScheduleSentence('daily', 0) ?? ''
    assert.match(s, /every day\./)
    assert.ok(!s.includes('about'))
  })

  test('an absent or manual schedule invents nothing', () => {
    assert.equal(payoutScheneNull(), null)
    assert.equal(payoutScheduleSentence('manual', 2), null)
    assert.equal(payoutScheduleSentence('fortnightly', 2), null)
  })

  function payoutScheneNull() {
    return payoutScheduleSentence(null, null)
  }

  test('ready shows no schedule note when Stripe gave none', () => {
    const view = describeConnect(status('ready', {
      transfers_status: 'active', transfers_enabled: true,
      payouts_status: 'active', payouts_enabled: true,
      payout_interval: null, payout_delay_days: null,
    }))
    assert.equal(view.scheduleNote, null)
  })
})

describe('fee disclosure', () => {
  test('states the order: Stripe first, then FC, then the creator', () => {
    const text = feeDisclosure(800)
    const stripeAt = text.indexOf('Stripe’s processing fee')
    const fcAt = text.indexOf('Fresh Collective’s plan fee')
    const creatorAt = text.indexOf('paid to you')
    assert.ok(stripeAt >= 0 && fcAt > stripeAt && creatorAt > fcAt, text)
  })

  test('a 0% plan is told the 0% is FC’s share, not Stripe’s fee', () => {
    const text = feeDisclosure(0)
    assert.match(text, /0% fee is Fresh Collective’s share/)
    assert.match(text, /Stripe’s\s+processing fee still applies/)
  })

  test('a 0% plan still gets the Stripe-fee disclosure', () => {
    assert.match(feeDisclosure(0), /Stripe’s processing fee comes out of each sale/)
  })

  test('no percentages, amounts or pricing tables are quoted', () => {
    for (const bps of [0, 800, null]) {
      const text = feeDisclosure(bps)
      assert.ok(!/\d+\.\d+%/.test(text), text)
      assert.ok(!/\$\d/.test(text), text)
      assert.ok(!/1\.7|2\.9|30c|0\.30/.test(text), text)
    }
  })

  test('an unknown plan fee still discloses the order', () => {
    assert.match(feeDisclosure(null), /Stripe’s processing fee comes out of each sale/)
  })
})

describe('nothing unsafe reaches the creator', () => {
  test('no account id, mode, or raw requirement payload appears in the copy', () => {
    const view = describeConnect(status('action_required', {
      stripe_account_id: 'acct_SECRET123',
      stripe_mode: 'live',
      details_submitted: true,
      requirements: [{
        description: 'identity.individual.id_number',
        awaiting_action_from: 'user',
        restricts_capabilities: ['stripe_balance.payouts'],
        errors: [{ code: 'verification_failed_other', reason: 'internal detail' }],
      }],
      last_error_message: 'Stripe 500: internal trace abc123',
    }))
    const text = [
      view.badge, view.headline, view.body, view.routingNote, view.scheduleNote,
    ].join(' ')
    assert.ok(!text.includes('acct_SECRET123'), text)
    assert.ok(!text.includes('live'), text)
    assert.ok(!text.includes('identity.individual.id_number'), text)
    assert.ok(!text.includes('verification_failed_other'), text)
    assert.ok(!text.includes('abc123'), text)
    assert.ok(!text.includes('stripe_balance'), text)
  })
})
