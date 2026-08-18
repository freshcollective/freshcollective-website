/**
 * FIP4B1 — unit tests for the plan-recovery copy composer.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import
import { planRecoveryCopy } from './planRecoveryCopy.ts'

const paymentProblemState = (overrides = {}) => ({
  status: 'payment_problem' as const,
  payment_option_name: 'FIP4A Test Access',
  installments_paid: 1,
  installments_expected: 3,
  grace_expires_at: '2026-08-25T00:00:00Z',
  suspended_at: null,
  recovery_required: true,
  ...overrides,
})

const suspendedState = (overrides = {}) => ({
  status: 'suspended' as const,
  payment_option_name: 'FIP4A Test Access',
  installments_paid: 1,
  installments_expected: 3,
  grace_expires_at: '2026-08-20T00:00:00Z',
  suspended_at: '2026-08-20T00:00:00Z',
  recovery_required: true,
  ...overrides,
})

describe('planRecoveryCopy — payment_problem', () => {
  test('warm headline + calm body + grace date', () => {
    const c = planRecoveryCopy(paymentProblemState(), 'Australia/Sydney')
    assert.equal(c.headline, 'Your payment needs attention')
    assert.ok(c.body.includes('FIP4A Test Access'))
    assert.ok(c.body.includes('Your access is still active until'))
    assert.ok(c.body.includes('before then'))
    assert.ok(c.body.includes('August'))
    assert.equal(c.progress, '1 of 3 paid')
    assert.equal(c.ctaDisabled, true)
  })

  test('formats grace date in Collective timezone', () => {
    // 2026-08-25T00:00:00Z → 10:00 AEST → still 25 August in Sydney
    const c = planRecoveryCopy(paymentProblemState(), 'Australia/Sydney')
    assert.ok(c.body.includes('25 August 2026'))
    assert.ok(c.body.includes('still active until 25 August 2026'))
  })

  test('falls back gracefully when grace date is missing', () => {
    const c = planRecoveryCopy(
      paymentProblemState({ grace_expires_at: null }),
      'Australia/Sydney',
    )
    // No "before <date>" clause added.
    assert.ok(!c.body.includes('before then'))
    assert.ok(!c.body.includes('still active until'))
    assert.ok(c.body.includes('still have access for now'))
  })

  test('falls back to browser locale for invalid timezone', () => {
    // Should not crash on garbage timezone.
    const c = planRecoveryCopy(paymentProblemState(), '__nope__')
    assert.ok(c.body.includes('August'))
  })

  test('missing option name uses friendly default', () => {
    const c = planRecoveryCopy(
      paymentProblemState({ payment_option_name: null }),
      null,
    )
    assert.ok(c.body.includes('your payment plan'))
  })
})

describe('planRecoveryCopy — suspended', () => {
  test('firmer headline + paused-access body + progress + disabled CTA', () => {
    const c = planRecoveryCopy(suspendedState(), null)
    assert.equal(c.headline, 'Your payment plan needs attention')
    assert.ok(c.body.includes('paused'))
    assert.ok(c.body.includes('restore access'))
    assert.equal(c.progress, '1 of 3 paid')
    assert.equal(c.ctaDisabled, true)
  })

  test('does not mention a date clause (no grace to warn about)', () => {
    const c = planRecoveryCopy(suspendedState(), null)
    assert.ok(!c.body.includes('before'))
  })
})
