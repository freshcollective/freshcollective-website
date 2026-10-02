/**
 * Refund gating — Connect rows, and the bug that hid the button.
 *
 * ``canRefund`` keyed everything on ``payout_status`` and returned false
 * for ``not_applicable``. Connect rows carry ``not_applicable``
 * correctly, so Refund was hidden on every Connect transaction — for
 * platform admins too. The backend had already named the trap in
 * ``_payout_gate_action``: "inferring from it would refuse every Connect
 * refund outright".
 *
 * The policy these pin is the revised one: an authorised creator-owner
 * may refund their own sale even after the transfer has gone out. The
 * backend's ``_connect_gate_action`` is the authority; this mirrors it so
 * the page does not offer a button that 403s, or hide one the policy
 * allows.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import
import { canRefundRow, isConnectRow, refundAdvisory } from './refundGating.ts'

const connectRow = (transfer: string, overrides = {}) => ({
  payment_provider: 'stripe',
  status: 'succeeded',
  gross_amount_cents: 200,
  refunded_amount_cents: 0,
  // Correct for a Connect row, and what used to hide the button.
  payout_status: 'not_applicable',
  payout_model: 'connect',
  connect: { status: transfer },
  ...overrides,
})

const manualRow = (payoutStatus: string, overrides = {}) => ({
  payment_provider: 'stripe',
  status: 'succeeded',
  gross_amount_cents: 200,
  refunded_amount_cents: 0,
  payout_status: payoutStatus,
  payout_model: 'manual',
  connect: null,
  ...overrides,
})

const BEFORE_TRANSFER = ['awaiting_payment', 'pending', 'failed', 'reversed']
const AFTER_TRANSFER = ['sent', 'partially_reversed']


describe('the reported bug: Connect rows showed no Refund at all', () => {
  test('not_applicable no longer hides the button on a Connect row', () => {
    const row = connectRow('sent')
    assert.equal(row.payout_status, 'not_applicable')
    assert.equal(canRefundRow(row, false), true)
    assert.equal(canRefundRow(row, true), true)
  })

  test('the production row is refundable by its creator', () => {
    // payout_model=connect, payout_status=not_applicable,
    // connect_transfer_status=sent — the live $2 sale.
    assert.equal(canRefundRow(connectRow('sent'), false), true)
  })
})


describe('Connect: before the transfer leaves', () => {
  for (const transfer of BEFORE_TRANSFER) {
    test(`${transfer} — creator may refund`, () => {
      assert.equal(canRefundRow(connectRow(transfer), false), true)
    })
    test(`${transfer} — admin may refund`, () => {
      assert.equal(canRefundRow(connectRow(transfer), true), true)
    })
    test(`${transfer} — no advisory, nothing is outstanding`, () => {
      assert.equal(refundAdvisory(connectRow(transfer)), 'none')
    })
  }
})


describe('Connect: after the transfer has gone out', () => {
  for (const transfer of AFTER_TRANSFER) {
    test(`${transfer} — the creator-owner may refund their own sale`, () => {
      // The policy change. Previously admin-only.
      assert.equal(canRefundRow(connectRow(transfer), false), true)
    })
    test(`${transfer} — admin may still refund`, () => {
      assert.equal(canRefundRow(connectRow(transfer), true), true)
    })
    test(`${transfer} — both actors get the reversal advisory`, () => {
      // The advisory describes the transaction, not who pressed the
      // button, so it must not depend on isPlatformOwner.
      assert.equal(refundAdvisory(connectRow(transfer)), 'connect_reversal')
    })
  }

  test('the advisory is NOT the manual-recovery one', () => {
    // Manual copy says FC will not recover. For Connect it will try —
    // the wrong warning here is alarming in the wrong direction.
    assert.notEqual(refundAdvisory(connectRow('sent')), 'manual_recovery')
  })
})


describe('Connect: states that are never refundable', () => {
  test('an unrecognised transfer status refuses, for everyone', () => {
    assert.equal(canRefundRow(connectRow('some_future_state'), true), false)
    assert.equal(canRefundRow(connectRow('some_future_state'), false), false)
  })

  test('a missing connect block refuses rather than guessing', () => {
    const row = connectRow('sent', { connect: null })
    assert.equal(canRefundRow(row, true), false)
  })

  test('a fully refunded row has nothing left to refund', () => {
    assert.equal(
      canRefundRow(connectRow('sent', { refunded_amount_cents: 200 }), true),
      false,
    )
  })

  test('a non-Stripe row is never refundable here', () => {
    assert.equal(
      canRefundRow(connectRow('sent', { payment_provider: 'manual' }), true),
      false,
    )
  })

  test('a failed transaction is not refundable', () => {
    assert.equal(
      canRefundRow(connectRow('sent', { status: 'failed' }), true),
      false,
    )
  })
})


describe('manual rows keep their existing restriction', () => {
  test('pending — creator may refund', () => {
    assert.equal(canRefundRow(manualRow('pending'), false), true)
  })

  test('paid — admin only, unchanged', () => {
    assert.equal(canRefundRow(manualRow('paid'), false), false)
    assert.equal(canRefundRow(manualRow('paid'), true), true)
  })

  test('held — admin only, unchanged', () => {
    assert.equal(canRefundRow(manualRow('held'), false), false)
    assert.equal(canRefundRow(manualRow('held'), true), true)
  })

  test('not_applicable on a manual row still refuses', () => {
    // Defensive: it should not occur on a refundable member payment.
    assert.equal(canRefundRow(manualRow('not_applicable'), true), false)
  })

  test('a paid manual row gets the manual-recovery advisory', () => {
    assert.equal(refundAdvisory(manualRow('paid')), 'manual_recovery')
    assert.equal(refundAdvisory(manualRow('held')), 'manual_recovery')
    assert.equal(refundAdvisory(manualRow('pending')), 'none')
  })

  test('relaxing Connect did not relax manual', () => {
    // The one thing this change must not have leaked into.
    assert.equal(canRefundRow(manualRow('paid'), false), false)
  })
})


describe('isConnectRow', () => {
  test('keys on payout_model, not on the presence of a connect block', () => {
    assert.equal(isConnectRow(connectRow('sent')), true)
    assert.equal(isConnectRow(manualRow('pending')), false)
    assert.equal(isConnectRow(manualRow('pending', { payout_model: undefined })), false)
  })
})


// ---------------------------------------------------------------------------
// The immediate toast
// ---------------------------------------------------------------------------

// @ts-expect-error - Node-native import
import { refundToast } from './refundGating.ts'

const accepted = { terminal_status: 'accepted', stripe_refund_id: 're_1', message: '' }
const confirmed = { terminal_status: 'webhook_confirmed', stripe_refund_id: 're_1', message: '' }

describe('refundToast', () => {
  test('a Connect post-transfer refund does NOT claim manual recovery', () => {
    // The reported bug. FC is about to attempt the reversal
    // automatically; saying otherwise is wrong at the moment it is said.
    const { text } = refundToast(accepted, 'connect_reversal')
    assert.ok(!text.toLowerCase().includes('manual recovery'))
    assert.ok(!text.toLowerCase().includes('manual follow-up'))
  })

  test('it says the refund was initiated and recovery will be attempted', () => {
    const { text } = refundToast(accepted, 'connect_reversal')
    assert.match(text, /Refund initiated/)
    assert.match(text, /automatically attempt to recover the creator’s transfer/)
  })

  test('a Connect refund reads as success, not as a warning', () => {
    // Nothing has gone wrong yet, and colouring it amber would teach an
    // operator to discount the colour when something has.
    assert.equal(refundToast(accepted, 'connect_reversal').tone, 'success')
  })

  test('a manual post-payout refund still says manual follow-up', () => {
    // Unchanged, because there the claim is true when it is made:
    // nothing automatic will recover that money.
    const toast = refundToast(accepted, 'manual_recovery')
    assert.match(toast.text, /manual follow-up/)
    assert.equal(toast.tone, 'attention')
  })

  test('no advisory means no extra sentence', () => {
    const { text } = refundToast(accepted, 'none')
    assert.match(text, /Refund initiated/)
    assert.ok(!text.includes('recover'))
  })

  test('a confirmed refund names the Stripe id', () => {
    assert.match(refundToast(confirmed, 'none').text, /Refund confirmed — re_1/)
  })

  test('a confirmed refund with no id does not print "no Stripe id"', () => {
    const { text } = refundToast(
      { terminal_status: 'webhook_confirmed', stripe_refund_id: null }, 'none',
    )
    assert.ok(!text.includes('no Stripe id'))
    assert.match(text, /Refund confirmed\./)
  })

  test('an unexpected status falls back to the backend message', () => {
    const { text } = refundToast(
      { terminal_status: 'refused', message: 'Stripe refused the refund.' }, 'none',
    )
    assert.equal(text, 'Stripe refused the refund.')
  })

  test('an empty message still says something', () => {
    assert.ok(refundToast({ terminal_status: 'weird', message: '' }, 'none').text.length > 0)
  })
})
