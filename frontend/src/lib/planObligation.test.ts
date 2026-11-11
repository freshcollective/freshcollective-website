import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  billingHasEnded,
  endedRemainingLabel,
  planObligation,
  uncollectedNote,
} from './planObligation.ts'

describe('a live plan still owes what it owes', () => {
  for (const status of ['active', 'pending_setup']) {
    test(`${status} reports its outstanding balance`, () => {
      const o = planObligation(status, 500)
      assert.equal(o.collectible, true)
      assert.equal(o.collectibleCents, 500)
      assert.equal(o.uncollectedCents, 0)
    })
  }

  test('payment_problem is behind, not finished', () => {
    const o = planObligation('payment_problem', 500)
    assert.equal(o.collectible, true)
    assert.equal(o.collectibleCents, 500)
  })

  test('suspended can still return to active, so it still owes', () => {
    // §14 — do not claim a plan has ended when it has not.
    const o = planObligation('suspended', 500)
    assert.equal(o.collectible, true)
    assert.equal(o.collectibleCents, 500)
    assert.equal(billingHasEnded('suspended'), false)
  })
})

describe('an ended plan collects nothing further', () => {
  test('the production case: cancelled and refunded shows no debt', () => {
    const o = planObligation('cancelled', 500)
    assert.equal(o.collectible, false)
    assert.equal(o.collectibleCents, 0)
    // The history survives — A$5 of the A$10 agreement was never paid.
    assert.equal(o.uncollectedCents, 500)
  })

  test('completed owes nothing and has nothing outstanding', () => {
    const o = planObligation('completed', 0)
    assert.equal(o.collectible, false)
    assert.equal(o.collectibleCents, 0)
    assert.equal(o.uncollectedCents, 0)
  })

  test('failed setup collects nothing', () => {
    const o = planObligation('failed', 1000)
    assert.equal(o.collectibleCents, 0)
    assert.equal(o.uncollectedCents, 1000)
  })

  test('a negative or missing figure never becomes a credit', () => {
    assert.equal(planObligation('cancelled', -50).uncollectedCents, 0)
    assert.equal(planObligation('active', undefined as never).collectibleCents, 0)
  })
})

describe('what the creator is told', () => {
  test('each ended status says which ending it was', () => {
    assert.equal(endedRemainingLabel('cancelled'), 'No further payments — cancelled')
    assert.equal(endedRemainingLabel('completed'), 'No further payments — completed')
    assert.equal(endedRemainingLabel('failed'), 'No further payments — setup failed')
  })

  test('a live plan gets no ended label', () => {
    assert.equal(endedRemainingLabel('active'), null)
    assert.equal(endedRemainingLabel('suspended'), null)
  })

  test('money left on the table is stated, once', () => {
    assert.equal(
      uncollectedNote(planObligation('cancelled', 500), 'A$5'),
      'A$5 agreed but not collected',
    )
  })

  test('a plan that paid in full says nothing about shortfalls', () => {
    assert.equal(uncollectedNote(planObligation('completed', 0), 'A$0'), null)
  })

  test('a live plan says nothing about shortfalls either', () => {
    assert.equal(uncollectedNote(planObligation('active', 500), 'A$5'), null)
  })
})
