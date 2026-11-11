import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  coveredByLabel,
  coveredHeading,
  optionCardState,
  ticketCardBlocksPurchase,
  ticketCardState,
  viewerOptionStatus,
  type BookingOriginLike,
} from './gatheringPurchaseStatus.ts'

const OPTION_ID = 'po_test_gathering_experience'

const fromOption: BookingOriginLike = {
  kind: 'payment_option',
  payment_option_id: OPTION_ID,
  payment_option_name: 'Test Gathering Experience',
}
const fromTicket: BookingOriginLike = { kind: 'direct_ticket' }
const fromPass: BookingOriginLike = { kind: 'series_pass' }
const fromCreator: BookingOriginLike = { kind: 'creator_manual' }

describe('the individual ticket card speaks only for itself', () => {
  test('a ticket bought here reads as purchased', () => {
    assert.equal(ticketCardState('confirmed', fromTicket), 'purchased')
  })

  test('a ticket being bought here reads as pending', () => {
    assert.equal(ticketCardState('pending_payment', fromTicket), 'pending')
  })

  test('a place earned by a Payment Option is not a ticket purchase', () => {
    // The production defect, after the plan completed.
    assert.equal(ticketCardState('confirmed', fromOption), 'covered')
  })

  test('a seat held by an instalment checkout is not a pending ticket', () => {
    // The production defect, during the checkout.
    assert.equal(ticketCardState('pending_payment', fromOption), 'held_elsewhere')
  })

  test('a Series pass place is not a ticket purchase', () => {
    assert.equal(ticketCardState('confirmed', fromPass), 'covered')
  })

  test('a caretaker-added place is not a ticket purchase', () => {
    assert.equal(ticketCardState('confirmed', fromCreator), 'covered')
  })

  test('no booking is available to buy', () => {
    assert.equal(ticketCardState(null, null), 'available')
  })

  test('a cancelled booking is available again', () => {
    assert.equal(ticketCardState('cancelled', fromTicket), 'available')
  })

  test('a missing origin keeps the old single-route behaviour', () => {
    // Every Gathering without Payment Options has one way in, and
    // every client before this field assumed exactly this.
    assert.equal(ticketCardState('confirmed', null), 'purchased')
    assert.equal(ticketCardState('pending_payment', undefined), 'pending')
  })
})

describe('a place the card did not sell still blocks a second purchase', () => {
  test('every state but available blocks', () => {
    for (const s of ['purchased', 'pending', 'covered', 'held_elsewhere'] as const) {
      assert.equal(ticketCardBlocksPurchase(s), true, s)
    }
    assert.equal(ticketCardBlocksPurchase('available'), false)
  })
})

describe('a Payment Option card speaks only for its own option', () => {
  test('the option that earned the place shows purchased', () => {
    assert.equal(optionCardState('confirmed', fromOption, OPTION_ID), 'purchased')
  })

  test('the option being bought shows pending', () => {
    assert.equal(optionCardState('pending_payment', fromOption, OPTION_ID), 'pending')
  })

  test('a different option shows nothing', () => {
    assert.equal(optionCardState('confirmed', fromOption, 'po_other'), null)
  })

  test('a direct ticket place never lights up an option card', () => {
    assert.equal(optionCardState('confirmed', fromTicket, OPTION_ID), null)
  })

  test('a Series pass place never lights up an option card', () => {
    assert.equal(optionCardState('confirmed', fromPass, OPTION_ID), null)
  })

  test('a cancelled booking lights up nothing', () => {
    assert.equal(optionCardState('cancelled', fromOption, OPTION_ID), null)
  })

  test('an unnamed option id cannot match', () => {
    assert.equal(optionCardState('confirmed', fromOption, null), null)
    assert.equal(
      optionCardState('confirmed', { kind: 'payment_option' }, OPTION_ID),
      null,
    )
  })
})

describe('what the member is told about where their place came from', () => {
  test('a named option is named', () => {
    assert.equal(
      coveredByLabel(fromOption),
      'Included with Test Gathering Experience',
    )
  })

  test('an option with no name says nothing rather than something empty', () => {
    assert.equal(
      coveredByLabel({ kind: 'payment_option', payment_option_id: 'x', payment_option_name: '  ' }),
      null,
    )
  })

  test('a Series pass is named generically', () => {
    assert.equal(coveredByLabel(fromPass), 'Included with your Series pass')
  })

  test('a caretaker-added place is left unexplained', () => {
    assert.equal(coveredByLabel(fromCreator), null)
    assert.equal(coveredByLabel({ kind: 'other' }), null)
  })

  test('the heading is about attendance, not paperwork', () => {
    assert.equal(coveredHeading('covered'), 'Your place is confirmed')
    assert.equal(coveredHeading('held_elsewhere'), 'Your place is being held')
    assert.equal(coveredHeading('purchased'), null)
    assert.equal(coveredHeading('available'), null)
  })
})

describe('the status crosses the server/client boundary as data', () => {
  test('a pending option purchase travels with its own id', () => {
    assert.deepEqual(
      viewerOptionStatus('pending_payment', fromOption),
      { paymentOptionId: OPTION_ID, state: 'pending' },
    )
  })

  test('a completed option purchase travels with its own id', () => {
    assert.deepEqual(
      viewerOptionStatus('confirmed', fromOption),
      { paymentOptionId: OPTION_ID, state: 'purchased' },
    )
  })

  test('a direct ticket sends nothing to the option cards', () => {
    assert.equal(viewerOptionStatus('confirmed', fromTicket), null)
  })

  test('a Series pass sends nothing to the option cards', () => {
    assert.equal(viewerOptionStatus('confirmed', fromPass), null)
  })

  test('no booking sends nothing', () => {
    assert.equal(viewerOptionStatus(null, null), null)
  })

  test('a cancelled booking sends nothing', () => {
    assert.equal(viewerOptionStatus('cancelled', fromOption), null)
  })

  test('the result is plain JSON — it has to survive serialisation', () => {
    const v = viewerOptionStatus('pending_payment', fromOption)
    assert.deepEqual(JSON.parse(JSON.stringify(v)), v)
  })
})
