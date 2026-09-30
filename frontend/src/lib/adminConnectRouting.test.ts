/**
 * The admin Connect-routing decision table.
 *
 * The field names and blocker codes here mirror the backend's
 * ``ConnectReadinessResponse`` and the constants in
 * ``connect_routing_enablement`` exactly, so a backend rename shows up as
 * a failure here rather than as an admin reading a fallback message.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import
import {
  describeRouting,
  errorMessageFrom,
  explainBlocker,
  formatEnabledAt,
} from './adminConnectRouting.ts'

const readiness = (overrides: Record<string, unknown> = {}) => ({
  creator_user_id: 'usr_1',
  stripe_mode: 'test',
  ready_to_enable: false,
  blockers: [],
  onboarding_state: null,
  payouts_status: null,
  payouts_enabled: false,
  has_stripe_account: false,
  fee_disclosure_acknowledged: false,
  fee_disclosure_version: null,
  routing_enabled_at: null,
  ...overrides,
})

const READY = {
  ready_to_enable: true,
  blockers: [],
  onboarding_state: 'ready',
  payouts_status: 'active',
  payouts_enabled: true,
  has_stripe_account: true,
  fee_disclosure_acknowledged: true,
  fee_disclosure_version: 'v1',
}

describe('the three states', () => {
  test('not ready offers no action at all', () => {
    const view = describeRouting(readiness({
      blockers: ['payouts_status_not_active'],
    }))
    assert.equal(view.action, 'none')
    assert.equal(view.actionLabel, null)
    assert.equal(view.confirmPrompt, null)
    assert.equal(view.badge, 'Not ready')
  })

  test('ready and not enabled offers Enable, and only Enable', () => {
    const view = describeRouting(readiness(READY))
    assert.equal(view.action, 'enable')
    assert.match(view.actionLabel ?? '', /Enable Connect routing/)
    assert.deepEqual(view.blockers, [])
    assert.equal(view.badge, 'Ready to enable')
  })

  test('enabled offers Disable and says when it was enabled', () => {
    const view = describeRouting(readiness({
      ...READY,
      routing_enabled_at: '2026-09-30T04:00:00Z',
    }))
    assert.equal(view.action, 'disable')
    assert.match(view.actionLabel ?? '', /Disable Connect routing/)
    assert.equal(view.badge, 'Routing live')
    assert.match(view.summary, /2026/)
  })

  test('a live creator who has since picked up a blocker can still be stopped', () => {
    // Otherwise an admin can see routing running and be unable to stop it.
    const view = describeRouting(readiness({
      ...READY,
      ready_to_enable: false,
      payouts_status: 'restricted',
      blockers: ['payouts_status_not_active'],
      routing_enabled_at: '2026-09-30T04:00:00Z',
    }))
    assert.equal(view.action, 'disable')
  })

  test('nothing about a readiness snapshot ever produces an enable by itself', () => {
    // The view is the only thing the card reads to decide what to render,
    // so "never auto-enable" is a property of this function.
    for (const state of [
      readiness(),
      readiness({ has_stripe_account: true }),
      readiness({ ...READY, ready_to_enable: false }),
      readiness({ fee_disclosure_acknowledged: true }),
      readiness({ payouts_enabled: true, payouts_status: 'active' }),
    ]) {
      assert.notEqual(describeRouting(state).action, 'enable')
    }
  })
})

describe('what the admin is told before acting', () => {
  test('both confirmations say purchases in flight are untouched', () => {
    const enable = describeRouting(readiness(READY))
    const disable = describeRouting(readiness({ ...READY, routing_enabled_at: '2026-09-30T04:00:00Z' }))
    for (const view of [enable, disable]) {
      assert.match(view.confirmPrompt ?? '', /already created/)
      assert.match(view.confirmPrompt ?? '', /in flight/)
    }
  })

  test('an unenabled creator is told their money still goes the manual way', () => {
    assert.match(describeRouting(readiness(READY)).summary, /manual payout process/)
    assert.match(
      describeRouting(readiness({ blockers: ['payouts_not_enabled'] })).summary,
      /manual payout process/,
    )
  })
})

describe('blockers in plain English', () => {
  const CODES = [
    'no_account_for_current_mode',
    'no_stripe_account_id',
    'payouts_status_not_active',
    'payouts_not_enabled',
    'fee_disclosure_not_acknowledged',
  ]

  test('every backend code has real prose, not the code itself', () => {
    for (const code of CODES) {
      const text = explainBlocker(code, 'live')
      assert.ok(text.length > 20, `${code} has no explanation`)
      assert.ok(!text.includes(code), `${code} leaked its raw code`)
    }
  })

  test('the missing-account message names the Stripe mode', () => {
    assert.match(explainBlocker('no_account_for_current_mode', 'live'), /live-mode/)
    assert.match(explainBlocker('no_account_for_current_mode', 'test'), /test-mode/)
  })

  test('the two creator-only conditions say the admin cannot do them', () => {
    assert.match(explainBlocker('no_account_for_current_mode', 'test'), /cannot be done for them/)
    assert.match(explainBlocker('fee_disclosure_not_acknowledged', 'test'), /Only they can do this/)
  })

  test('a code this build has never seen still renders something', () => {
    const text = explainBlocker('some_future_condition', 'test')
    assert.ok(text.length > 0)
    assert.match(text, /some_future_condition/)
  })

  test('blockers reach the view already translated', () => {
    const view = describeRouting(readiness({
      blockers: ['payouts_not_enabled', 'fee_disclosure_not_acknowledged'],
    }))
    assert.equal(view.blockers.length, 2)
    for (const b of view.blockers) {
      assert.ok(!b.includes('_'), `raw code leaked: ${b}`)
    }
  })
})

describe('the status facts', () => {
  test('an untouched creator reads as absent, not as false', () => {
    const view = describeRouting(readiness())
    const value = (label: string) => view.facts.find((f) => f.label === label)?.value
    assert.equal(value('Stripe account'), 'None')
    assert.equal(value('Onboarding'), 'Not started')
    assert.equal(value('Payouts'), 'Unknown')
    assert.equal(value('Fee acknowledgement'), 'Not acknowledged')
  })

  test('the acknowledgement fact carries the version that was agreed to', () => {
    const view = describeRouting(readiness({
      fee_disclosure_acknowledged: true, fee_disclosure_version: 'v2',
    }))
    assert.equal(
      view.facts.find((f) => f.label === 'Fee acknowledgement')?.value,
      'Acknowledged (v2)',
    )
  })

  test('an active-but-not-enabled payout state is not read as fine', () => {
    const view = describeRouting(readiness({
      payouts_status: 'active', payouts_enabled: false,
    }))
    assert.match(view.facts.find((f) => f.label === 'Payouts')?.value ?? '', /not enabled/)
  })

  test('the Stripe mode is on the account fact, since routing is per mode', () => {
    const view = describeRouting(readiness({ has_stripe_account: true, stripe_mode: 'live' }))
    assert.match(view.facts.find((f) => f.label === 'Stripe account')?.value ?? '', /live/)
  })
})

describe('formatEnabledAt', () => {
  test('null and unparseable input produce nothing rather than "Invalid Date"', () => {
    assert.equal(formatEnabledAt(null), '')
    assert.equal(formatEnabledAt('not a date'), '')
  })

  test('a naive backend timestamp is read as UTC, not as local time', () => {
    // The backend isoformats a naive UTC datetime, so it arrives with no
    // offset. Reading it as local would shift it by the viewer's offset.
    const naive = formatEnabledAt('2026-09-30T04:00:00')
    const explicit = formatEnabledAt('2026-09-30T04:00:00Z')
    assert.equal(naive, explicit)
    assert.notEqual(naive, '')
  })
})

describe('errorMessageFrom', () => {
  test('a 409 shows the backend message, which is already written for a person', () => {
    const message = errorMessageFrom(409, {
      detail: {
        reason: 'fee_disclosure_not_acknowledged',
        message: 'This creator has not acknowledged the fee model.',
      },
    })
    assert.equal(message, 'This creator has not acknowledged the fee model.')
  })

  test('a detail object without a message falls back to the reason, not [object Object]', () => {
    const message = errorMessageFrom(409, { detail: { reason: 'payouts_not_enabled' } })
    assert.ok(!message.includes('[object Object]'))
    assert.match(message, /payouts_not_enabled/)
  })

  test('a plain string detail is used as-is', () => {
    assert.equal(errorMessageFrom(400, { detail: 'Bad request.' }), 'Bad request.')
  })

  test('an empty body still yields something an admin can act on', () => {
    assert.match(errorMessageFrom(409, null), /Refresh and try again/)
    assert.match(errorMessageFrom(403, null), /permission/)
    assert.match(errorMessageFrom(404, null), /could not be found/)
    assert.match(errorMessageFrom(500, null), /HTTP 500/)
  })

  test('a blank message does not produce an empty error box', () => {
    const message = errorMessageFrom(409, { detail: { reason: '  ', message: '   ' } })
    assert.ok(message.trim().length > 0)
  })
})
