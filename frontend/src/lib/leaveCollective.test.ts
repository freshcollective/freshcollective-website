import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  canOfferLeave,
  departureBlockedMessage,
  departureConsequenceLines,
  type DeparturePreview,
} from './leaveCollective.ts'

const SRC = dirname(fileURLToPath(import.meta.url))

function preview(over: Partial<DeparturePreview> = {}): DeparturePreview {
  return {
    can_leave: true,
    blocked_reason: null,
    live_payment_plans: 0,
    active_passes: 0,
    unused_credits: 0,
    future_bookings: 0,
    purchased_future_bookings: 0,
    purchased_pathways: 0,
    membership_gated_paid_pathways: 0,
    offerings_retained: 0,
    ...over,
  }
}

const joined = (p: DeparturePreview) => departureConsequenceLines(p).join(' ')

describe('who is offered the action', () => {
  test('a Member is', () => {
    assert.equal(canOfferLeave('learner'), true)
  })

  test('a Creator is not', () => {
    assert.equal(canOfferLeave('creator'), false)
  })

  test('a Moderator is not', () => {
    // They manage the Collective. The server refuses them too, with
    // ``caretaker_role`` — this keeps the button from appearing at all.
    assert.equal(canOfferLeave('moderator'), false)
  })

  test('an unknown role is not', () => {
    // Fail closed: a role this build has not heard of does not get a
    // destructive action.
    assert.equal(canOfferLeave('observer'), false)
  })
})

describe('refusals', () => {
  test('a leavable membership has no blocked message', () => {
    assert.equal(departureBlockedMessage(preview()), null)
  })

  test('a live payment plan explains itself and points at the creator', () => {
    const msg = departureBlockedMessage(
      preview({
        can_leave: false,
        blocked_reason: 'live_payment_plan',
        live_payment_plans: 1,
      }),
    )
    assert.match(String(msg), /payment plan in progress/)
    assert.match(String(msg), /creator/)
    // The reason it refuses rather than proceeding.
    assert.match(String(msg), /charged for access you no longer have/)
  })

  test('the plan message reads correctly for more than one', () => {
    const msg = String(departureBlockedMessage(
      preview({
        can_leave: false,
        blocked_reason: 'live_payment_plan',
        live_payment_plans: 2,
      }),
    ))
    assert.match(msg, /payment plans in progress/)
  })

  test('a caretaker is sent to Creator Studio', () => {
    const msg = String(departureBlockedMessage(
      preview({ can_leave: false, blocked_reason: 'caretaker_role' }),
    ))
    assert.match(msg, /Creator Studio/)
  })

  test('an auto-managed Collective says so', () => {
    const msg = String(departureBlockedMessage(
      preview({
        can_leave: false, blocked_reason: 'auto_managed_collective',
      }),
    ))
    assert.match(msg, /managed automatically/)
  })

  test('a stale card is handled', () => {
    const msg = String(departureBlockedMessage(
      preview({ can_leave: false, blocked_reason: 'not_a_member' }),
    ))
    assert.match(msg, /not currently a member/)
  })

  test('an unrecognised reason still refuses rather than falling through', () => {
    // A new server-side refusal must never render an empty dialog with
    // a working confirm button.
    const msg = departureBlockedMessage(
      preview({ can_leave: false, blocked_reason: 'something_new' }),
    )
    assert.ok(msg && msg.length > 0)
  })

  test('a null reason with can_leave false still refuses', () => {
    const msg = departureBlockedMessage(
      preview({ can_leave: false, blocked_reason: null }),
    )
    assert.ok(msg && msg.length > 0)
  })
})

describe('what the dialog says', () => {
  test('it always says what access is lost', () => {
    assert.match(
      departureConsequenceLines(preview())[0],
      /Pathways, Gatherings and member-only community spaces/,
    )
  })

  test('it always reassures about Your Collection', () => {
    assert.match(joined(preview()), /Your Collection/)
  })

  test('it counts the Offerings when there are some', () => {
    assert.match(
      joined(preview({ offerings_retained: 3 })),
      /The 3 Offerings you’ve acquired will stay in Your Collection/,
    )
  })

  test('one Offering reads as singular', () => {
    assert.match(
      joined(preview({ offerings_retained: 1 })),
      /The 1 Offering you’ve acquired/,
    )
  })

  test('the reassurance is the second-to-last thing said', () => {
    // Ends on what is kept, then the way back.
    const lines = departureConsequenceLines(preview({ offerings_retained: 2 }))
    assert.match(lines[lines.length - 2], /Your Collection/)
  })
})

describe('the way back', () => {
  test('it promises a rejoin, now that one exists', () => {
    // Safe because a voluntary departure records itself as such
    // (migration 166) and ``membership_grant.may_rejoin`` admits
    // exactly that case through the ordinary Join flow.
    assert.match(
      joined(preview()),
      /You can rejoin this Collective later, subject to its membership requirements\./,
    )
  })

  test('the promise is conditional, not absolute', () => {
    // Rejoining re-runs the join policy and the member allowance, so
    // the sentence must not read as an unconditional right.
    assert.match(joined(preview()), /subject to its membership requirements/)
  })

  test('the old permanence warning is gone', () => {
    const text = joined(preview({
      offerings_retained: 2, active_passes: 1, future_bookings: 1,
    }))
    assert.ok(!/permanent/i.test(text), text)
    assert.ok(!/isn’t supported yet/i.test(text))
  })

  test('it is the last thing said', () => {
    const lines = departureConsequenceLines(preview())
    assert.match(lines[lines.length - 1], /You can rejoin this Collective later/)
  })
})

describe('paid things are described as kept', () => {
  test('a pass is not described as cancelled or refunded', () => {
    const text = joined(preview({ active_passes: 1 }))
    assert.match(text, /not cancelled and not refunded/)
  })

  test('unused credits are mentioned when there are some', () => {
    assert.match(
      joined(preview({ active_passes: 1, unused_credits: 7 })),
      /7 unused credits will stay on them/,
    )
  })

  test('credits are not mentioned when there are none', () => {
    assert.ok(!/unused/.test(joined(preview({ active_passes: 1 }))))
  })

  test('a paid reservation is described as kept and reachable', () => {
    // The per-reservation exception makes this true: the Gathering
    // page opens for the holder even after they leave.
    const text = joined(preview({
      future_bookings: 1, purchased_future_bookings: 1,
    }))
    assert.match(text, /1 paid Gathering reservation stays yours/)
    assert.match(text, /not cancelled and not refunded/)
    assert.match(text, /still be able to see it and cancel/)
  })

  test('two paid reservations read as plural', () => {
    const text = joined(preview({
      future_bookings: 2, purchased_future_bookings: 2,
    }))
    assert.match(text, /2 paid Gathering reservations stay yours/)
  })

  test('a membership-derived booking is described as lost', () => {
    // It came with membership and goes with it — the exception
    // deliberately does not cover it.
    const text = joined(preview({
      future_bookings: 1, purchased_future_bookings: 0,
    }))
    assert.match(
      text,
      /1 upcoming booking that came with membership will no longer be available/,
    )
  })

  test('a mix describes both groups separately', () => {
    const text = joined(preview({
      future_bookings: 3, purchased_future_bookings: 1,
    }))
    assert.match(text, /1 paid Gathering reservation stays yours/)
    assert.match(text, /2 upcoming bookings that came with membership/)
  })

  test('no booking line at all when there are none', () => {
    const text = joined(preview())
    assert.ok(!/reservation/.test(text))
    assert.ok(!/came with membership/.test(text))
  })

  test('the old blanket warning is gone', () => {
    // "you may no longer be able to reach them" was true of neither
    // group once the exception existed.
    const text = joined(preview({
      future_bookings: 2, purchased_future_bookings: 1,
    }))
    assert.ok(!/no longer be able to reach/.test(text), text)
  })

  test('outright purchases are described as kept', () => {
    assert.match(
      joined(preview({ purchased_pathways: 2 })),
      /2 Pathways you bought outright will stay available/,
    )
  })

  test('nothing paid is mentioned when there is nothing paid', () => {
    const text = joined(preview())
    assert.ok(!/pass/.test(text))
    assert.ok(!/booking/.test(text))
    assert.ok(!/bought outright/.test(text))
  })
})

describe('membership-gated paid Pathways', () => {
  test('they get their own line, because they really are lost', () => {
    // ``included_with_offer`` is paid for but gated on active
    // membership, so this is the one case where leaving closes
    // something bought.
    const text = joined(preview({ membership_gated_paid_pathways: 2 }))
    assert.match(text, /unlocked with a paid offer/)
    assert.match(text, /leaving will close them/)
    assert.match(text, /Nothing is refunded/)
  })

  test('one reads as singular', () => {
    const text = joined(preview({ membership_gated_paid_pathways: 1 }))
    assert.match(text, /1 Pathway you unlocked with a paid offer needs/)
    assert.match(text, /close it/)
  })

  test('it is silent when there are none', () => {
    assert.ok(!/paid offer/.test(joined(preview())))
  })
})

describe('the component contract', () => {
  const component = readFileSync(
    join(SRC, '..', 'app', 'settings', 'membership', 'LeaveCollective.tsx'),
    'utf8',
  )
  const list = readFileSync(
    join(SRC, '..', 'app', 'settings', 'membership', 'CollectivesList.tsx'),
    'utf8',
  )

  test('a failed request never reports a departure', () => {
    // The ordering that matters: ``onLeft`` and the success toast must
    // sit after the ``!res.ok`` return, never before it.
    const okGuard = component.indexOf('if (!res.ok) {')
    const left = component.indexOf('onLeft(spaceSlug)')
    assert.ok(okGuard > 0 && left > okGuard)
  })

  test('it shows the server’s own refusal text when there is one', () => {
    assert.match(component, /body\?\.detail/)
  })

  test('the confirm button is hidden unless the server said it may leave', () => {
    assert.match(component, /canConfirm = Boolean\(preview\?\.can_leave\)/)
  })

  test('it deletes its own membership, naming no user', () => {
    assert.match(component, /\/my-membership`\)/)
    assert.ok(!/user_id/.test(component))
  })

  test('the list offers the action only through the shared predicate', () => {
    assert.match(list, /canOfferLeave\(m\.role\)/)
  })

  test('the list refreshes from the server after a departure', () => {
    assert.match(list, /router\.refresh\(\)/)
  })

  test('the card chrome is unchanged', () => {
    // Same shell as the server-rendered card it replaced.
    assert.match(list, /rounded-2xl border border-border bg-white px-6 py-4/)
    assert.match(list, /boxShadow: '0 1px 4px rgba\(0,0,0,0\.04\)'/)
  })

  test('the action is discoverable but not dominant', () => {
    // A quiet text button on the card; the danger variant is reserved
    // for the dialog, where the consequences are.
    assert.ok(!/variant="danger"[\s\S]{0,400}Leave Collective\s*<\/Button>\s*\)\s*}\s*<\/>/.test(list))
    assert.match(component, /text-\[12px\] font-medium text-black underline/)
  })

  const retained = readFileSync(
    join(SRC, '..', 'app', 'settings', 'membership', 'RetainedReservations.tsx'),
    'utf8',
  )

  test('the retained band renders nothing when there is nothing', () => {
    // Almost everybody. An empty band would put a permanent
    // "reservations" heading on every member's settings page.
    assert.match(retained, /reservations\.length === 0\) return null/)
  })

  test('each retained reservation links to its own Gathering', () => {
    assert.match(
      retained,
      /\/spaces\/\$\{r\.space_slug\}\/events\/\$\{r\.event_id\}/,
    )
  })

  test('the retained band explains why they still have it', () => {
    assert.match(retained, /You paid for these/)
  })

  test('the retained band offers no action at all', () => {
    // The exception is read-only, so this band links and nothing more.
    // Asserted on affordances rather than on the word "book", which
    // appears legitimately in the comments and in ``booking_id``.
    const code = retained
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '')
    assert.ok(!/<button/i.test(code), 'no button')
    assert.ok(!/onClick/.test(code), 'no handler')
    assert.ok(!/fetch\(/.test(code), 'no request')
    assert.ok(!/'use client'/.test(code), 'stays a server component')
  })

  test('no teal eyebrow label was introduced', () => {
    for (const file of [component, list, retained]) {
      assert.ok(!/uppercase tracking-\[0\.12em\] text-teal/.test(file))
    }
  })
})
