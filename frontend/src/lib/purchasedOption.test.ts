import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  hidesCheckout,
  planProgressLines,
  purchaseFor,
  purchasedHeading,
  purchasedStatusLine,
  purchasedTone,
  YOUR_WORLD,
  type MemberOptionPurchaseLike,
  type MemberPlanSummaryLike,
} from './purchasedOption.ts'

const OPTION = 'po_test_gathering_experience'
const fmt = (c: number, cur: string) =>
  `${cur === 'AUD' ? 'A$' : '$'}${(c / 100).toFixed(2).replace(/\.00$/, '')}`

/** Tom's agreement: 2 x A$3 after A$4 off 2 x A$5. */
function plan(over: Partial<MemberPlanSummaryLike> = {}): MemberPlanSummaryLike {
  return {
    status: 'active',
    currency: 'AUD',
    installment_amount_cents: 300,
    final_installment_amount_cents: null,
    installments_expected: 2,
    installments_paid: 1,
    total_expected_cents: 600,
    paid_amount_cents: 300,
    remaining_amount_cents: 300,
    interval: 'month',
    interval_count: 1,
    payment_option_schedule_id: 'sch_2x',
    ...over,
  }
}

function purchase(over: Partial<MemberOptionPurchaseLike> = {}): MemberOptionPurchaseLike {
  return {
    payment_option_id: OPTION,
    kind: 'plan',
    blocks_repurchase: true,
    plan: plan(),
    ...over,
  }
}

describe('finding the viewer’s purchase of one option', () => {
  test('it matches by id', () => {
    assert.equal(purchaseFor([purchase()], OPTION)?.payment_option_id, OPTION)
  })

  test('another option is unaffected', () => {
    assert.equal(purchaseFor([purchase()], 'po_other'), null)
  })

  test('nothing bought, nothing found', () => {
    assert.equal(purchaseFor([], OPTION), null)
    assert.equal(purchaseFor(null, OPTION), null)
    assert.equal(purchaseFor([purchase()], null), null)
  })
})

describe('when the card stops offering checkout', () => {
  test('the reported case: an active plan hides the buy buttons', () => {
    assert.equal(hidesCheckout(purchase()), true)
  })

  test('an unbought option keeps its buttons', () => {
    assert.equal(hidesCheckout(null), false)
  })

  test('a settled pay-in-full purchase hides them', () => {
    assert.equal(
      hidesCheckout({ payment_option_id: OPTION, kind: 'pay_in_full', blocks_repurchase: true }),
      true,
    )
  })

  test('the till’s verdict governs, so a legitimate repurchase stays open', () => {
    // A completed plan whose access has lapsed: the backend allows
    // buying again, so the UI must not forbid it.
    assert.equal(
      hidesCheckout(purchase({
        blocks_repurchase: false, plan: plan({ status: 'completed' }),
      })),
      false,
    )
    assert.equal(
      hidesCheckout(purchase({
        blocks_repurchase: false, plan: plan({ status: 'cancelled' }),
      })),
      false,
    )
    assert.equal(
      hidesCheckout(purchase({
        blocks_repurchase: false, plan: plan({ status: 'failed' }),
      })),
      false,
    )
  })

  test('a completed plan whose access is still live keeps them hidden', () => {
    // §8 — not offered another purchase merely because it completed.
    assert.equal(
      hidesCheckout(purchase({
        blocks_repurchase: true, plan: plan({ status: 'completed' }),
      })),
      true,
    )
  })

  test('a plan needing repair is not answered with "start another"', () => {
    for (const status of ['payment_problem', 'suspended']) {
      assert.equal(
        hidesCheckout(purchase({
          blocks_repurchase: false, plan: plan({ status }),
        })),
        true,
        status,
      )
    }
  })
})

describe('what the purchased card says', () => {
  test('an active plan has joined, not purchased-and-done', () => {
    const tone = purchasedTone(purchase())
    assert.equal(tone, 'joined')
    assert.equal(
      purchasedHeading(tone, 'Test Gathering Experience'),
      "You've joined Test Gathering Experience",
    )
    assert.equal(purchasedStatusLine(purchase()), 'Your payment plan is active.')
  })

  test('pending setup never claims the purchase is complete', () => {
    const p = purchase({ plan: plan({ status: 'pending_setup' }) })
    assert.equal(purchasedTone(p), 'setup')
    assert.equal(purchasedHeading('setup', 'X'), 'Payment setup in progress')
    assert.match(purchasedStatusLine(p)!, /Complete your payment setup/)
  })

  test('a suspended plan is not described as ended', () => {
    const p = purchase({ plan: plan({ status: 'suspended' }) })
    assert.equal(purchasedTone(p), 'attention')
    assert.match(purchasedStatusLine(p)!, /paused/)
    assert.doesNotMatch(purchasedStatusLine(p)!, /complete|cancelled/)
  })

  test('a cancelled plan is not described as active', () => {
    const p = purchase({ plan: plan({ status: 'cancelled' }) })
    assert.equal(purchasedTone(p), 'ended')
    assert.equal(purchasedStatusLine(p), 'This payment plan was cancelled.')
  })

  test('a failed setup does not claim access', () => {
    const p = purchase({ plan: plan({ status: 'failed' }) })
    assert.match(purchasedStatusLine(p)!, /didn’t complete/)
  })

  test('a completed plan says so', () => {
    const p = purchase({ plan: plan({ status: 'completed' }) })
    assert.equal(purchasedStatusLine(p), 'Your payment plan is complete.')
  })

  test('a pay-in-full purchase points at the experiences', () => {
    const p: MemberOptionPurchaseLike = {
      payment_option_id: OPTION, kind: 'pay_in_full', blocks_repurchase: true,
    }
    assert.equal(purchasedTone(p), 'joined')
    assert.equal(purchasedStatusLine(p), 'Your included experiences are ready.')
  })

  test('nothing bought, nothing said', () => {
    assert.equal(purchasedTone(null), null)
    assert.equal(purchasedHeading(null, 'X'), null)
    assert.equal(purchasedStatusLine(null), null)
  })
})

describe('the arrangement, as agreed', () => {
  test('the reported case shows A$3, not the option’s A$5', () => {
    const l = planProgressLines(plan(), fmt, 'monthly')!
    assert.equal(l.schedule, '2 monthly payments of A$3')
    assert.equal(l.total, 'A$6 total')
    assert.equal(l.progress, '1 of 2 payments completed')
    assert.equal(l.remaining, 'A$3 remaining')
  })

  test('an uneven final payment is named', () => {
    const l = planProgressLines(plan({
      installment_amount_cents: 4333, final_installment_amount_cents: 4334,
      installments_expected: 3, installments_paid: 0,
      total_expected_cents: 13000, remaining_amount_cents: 13000,
    }), fmt, 'monthly')!
    assert.equal(l.schedule, '2 monthly payments of A$43.33, then A$43.34')
    assert.equal(l.total, 'A$130 total')
    assert.ok(!l.schedule.includes('3 monthly payments of A$43.33'))
  })

  test('a two-payment uneven plan reads in the singular', () => {
    const l = planProgressLines(plan({
      final_installment_amount_cents: 301, total_expected_cents: 601,
    }), fmt, 'monthly')!
    assert.equal(l.schedule, '1 monthly payment of A$3, then A$3.01')
  })

  test('an ended plan shows no remaining figure', () => {
    for (const status of ['completed', 'cancelled', 'failed']) {
      const l = planProgressLines(plan({ status }), fmt, 'monthly')!
      assert.equal(l.remaining, null, status)
    }
  })

  test('a fully paid live plan shows no remaining figure either', () => {
    const l = planProgressLines(
      plan({ installments_paid: 2, paid_amount_cents: 600, remaining_amount_cents: 0 }),
      fmt, 'monthly',
    )!
    assert.equal(l.remaining, null)
    assert.equal(l.progress, '2 of 2 payments completed')
  })

  test('no plan, no lines', () => {
    assert.equal(planProgressLines(null, fmt, 'monthly'), null)
    assert.equal(planProgressLines(plan({ installments_expected: 0 }), fmt, 'monthly'), null)
  })
})

describe('where the member is sent', () => {
  test('Your World is a real route', () => {
    assert.equal(YOUR_WORLD.href, '/dashboard')
    assert.equal(YOUR_WORLD.label, 'Go to Your World')
  })
})
