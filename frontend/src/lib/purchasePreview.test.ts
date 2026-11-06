import { strict as assert } from 'node:assert'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  type PreviewArrangement,
  type PurchasePreview,
  accessExplanation,
  alsoIncluded,
  arrangementExplanation,
  arrangementPaymentLine,
  arrangementStatus,
  arrangementTitle,
  arrangementTotalLine,
  arrangementUpfrontLine,
  groupByOption,
  includedKindLabel,
} from './purchasePreview.ts'

/**
 * Stage 1B.1 — the creator-facing wording of a purchase arrangement.
 *
 * Tested against production-shaped rows rather than source text,
 * because the risk here is not that a string is missing: it is that a
 * $99 bundle and a 3 x $33 plan get collapsed into one figure, or that
 * an arrangement checkout would refuse is badged "Available". Both are
 * assertions about values, and both were real defects at some point in
 * this system's history.
 *
 * Deliberately NOT tested here: the prices themselves. Every figure
 * arrives from the resolver through the creator preview endpoint, and
 * `backend/tests/test_creator_purchase_preview.py` owns whether they
 * are right.
 */

function arrangement(
  over: Partial<PreviewArrangement> = {},
): PreviewArrangement {
  return {
    source: 'payment_option',
    name: 'Personal Leadership Bundle',
    schedule_name: 'Pay in full',
    schedule_type: 'pay_in_full',
    currency: 'AUD',
    total_amount_cents: 9900,
    upfront_amount_cents: 9900,
    installment_amount_cents: null,
    installment_count: null,
    interval: null,
    is_bundle: false,
    is_free: false,
    included: [],
    payment_option_id: 'po_1',
    available_for_new_purchase: true,
    unavailable_reason: null,
    configured_available: true,
    blocked_by_platform: false,
    is_historical_source: false,
    ...over,
  }
}

function preview(over: Partial<PurchasePreview> = {}): PurchasePreview {
  return {
    experience_kind: 'pathway',
    experience_id: 'pw_1',
    title: 'Personal Leadership',
    access_type: 'one_time',
    has_purchasable_arrangement: true,
    arrangements: [],
    ...over,
  }
}

const DIRECT = arrangement({
  source: 'direct',
  name: 'Personal Leadership',
  schedule_name: null,
  schedule_type: 'direct',
  total_amount_cents: 4900,
  upfront_amount_cents: 4900,
  payment_option_id: null,
})

const PLAN = arrangement({
  schedule_name: 'Payment plan',
  schedule_type: 'recurring_installments',
  total_amount_cents: 9900,
  upfront_amount_cents: 3300,
  installment_amount_cents: 3300,
  installment_count: 3,
  interval: 'week',
})

// ---------------------------------------------------------------------------

describe('a direct price reads as an individual purchase', () => {
  it('is named for how it is bought, not for the experience', () => {
    // The title is already the page heading; repeating it says
    // nothing about the money.
    assert.equal(arrangementTitle(DIRECT, 'pathway'), 'Individual purchase')
    assert.equal(arrangementTitle(DIRECT, 'gathering'), 'Individual ticket')
  })

  it('shows the price once, in the members wording', () => {
    assert.equal(arrangementPaymentLine(DIRECT), '$49 once')
  })

  it('has no total line — the payment line already carries it', () => {
    assert.equal(arrangementTotalLine(DIRECT), null)
  })

  it('names an unset price rather than printing a zero', () => {
    const unset = arrangement({
      source: 'direct',
      total_amount_cents: null,
      available_for_new_purchase: false,
      unavailable_reason: 'price_not_set',
    })
    assert.equal(arrangementPaymentLine(unset), 'No price set')
    // Never invented, never estimated.
    assert.ok(!arrangementPaymentLine(unset).includes('$'))
  })

  it('calls a zero price free', () => {
    const free = arrangement({ source: 'direct', total_amount_cents: 0 })
    assert.equal(arrangementPaymentLine(free), 'Free')
  })
})

describe('each schedule keeps its own price', () => {
  it('a pay-in-full schedule states the single amount', () => {
    assert.equal(arrangementPaymentLine(arrangement()), '$99 once')
  })

  it('an instalment schedule states the per-payment amount and cadence', () => {
    assert.equal(arrangementPaymentLine(PLAN), '3 weekly payments of $33')
  })

  it('and its total, so nobody multiplies in their head', () => {
    assert.equal(arrangementTotalLine(PLAN), '$99 total')
  })

  it('never reads the total as the per-payment amount', () => {
    // The confusion the resolver was built to make impossible: $99 is
    // the commitment, $33 is what leaves the account.
    const line = arrangementPaymentLine(PLAN)
    assert.ok(line.includes('$33'), line)
    assert.ok(!line.includes('$99'), line)
  })

  it('mentions a first charge only when it differs', () => {
    assert.equal(arrangementUpfrontLine(PLAN), null)
    const deposit = arrangement({
      ...PLAN,
      upfront_amount_cents: 5000,
    })
    assert.equal(arrangementUpfrontLine(deposit), '$50 to start')
  })

  it('two schedules on one Option stay two rows under one name', () => {
    const p = preview({
      arrangements: [DIRECT, arrangement(), PLAN],
    })
    const groups = groupByOption(p)
    assert.equal(groups.length, 1, 'the bundle was split or duplicated')
    assert.equal(groups[0].name, 'Personal Leadership Bundle')
    assert.equal(groups[0].schedules.length, 2)
    assert.deepEqual(
      groups[0].schedules.map(arrangementPaymentLine),
      ['$99 once', '3 weekly payments of $33'],
    )
  })

  it('keeps the direct price out of the Option groups', () => {
    const p = preview({ arrangements: [DIRECT, arrangement()] })
    assert.equal(groupByOption(p).length, 1)
  })

  it('preserves the order the API returned', () => {
    const second = arrangement({ payment_option_id: 'po_2', name: 'Second' })
    const p = preview({ arrangements: [arrangement(), second] })
    assert.deepEqual(groupByOption(p).map((g) => g.name), [
      'Personal Leadership Bundle', 'Second',
    ])
  })
})

describe('availability is reported honestly', () => {
  it('an available arrangement is Available with nothing to explain', () => {
    const a = arrangement()
    assert.deepEqual(arrangementStatus(a), { label: 'Available', tone: 'available' })
    assert.equal(arrangementExplanation(a, 'pathway'), null)
  })

  it('a draft Option is Draft, not Available', () => {
    const a = arrangement({
      available_for_new_purchase: false,
      configured_available: false,
      unavailable_reason: 'option_not_published',
    })
    assert.equal(arrangementStatus(a).label, 'Draft')
    assert.match(arrangementExplanation(a, 'pathway')!, /still a draft/)
  })

  it('a draft schedule is Draft too', () => {
    const a = arrangement({
      available_for_new_purchase: false,
      unavailable_reason: 'schedule_not_published',
    })
    assert.equal(arrangementStatus(a).label, 'Draft')
  })

  it('an archived Option is Archived, and says access is preserved', () => {
    const a = arrangement({
      available_for_new_purchase: false,
      unavailable_reason: 'option_archived',
      is_historical_source: true,
    })
    assert.deepEqual(arrangementStatus(a), { label: 'Archived', tone: 'archived' })
    const copy = arrangementExplanation(a, 'pathway')!
    assert.match(copy, /no longer offered to new members/)
    // The half a creator needs in order not to panic.
    assert.match(copy, /keeps their access/)
  })

  it('an unsupported Gathering inclusion is not purchasable', () => {
    // The explicit requirement: the resolver can identify the retreat
    // instalment plan, and it must not look buyable.
    const a = arrangement({
      name: 'Retreat Instalment Plan',
      schedule_type: 'recurring_installments',
      installment_amount_cents: 100000,
      installment_count: 3,
      interval: 'month',
      total_amount_cents: 300000,
      available_for_new_purchase: false,
      unavailable_reason: 'unsupported_inclusion',
    })
    assert.deepEqual(arrangementStatus(a), {
      label: 'Not purchasable yet', tone: 'pending',
    })
    const copy = arrangementExplanation(a, 'gathering')!
    assert.match(copy, /coming soon/)
    assert.match(copy, /cannot purchase/)
    // The figures are still shown — hiding them would hide the
    // creator's own configuration from them.
    assert.equal(arrangementPaymentLine(a), '3 monthly payments of $1000')
  })

  it('a missing price needs attention, which is a different thing', () => {
    const a = arrangement({
      available_for_new_purchase: false,
      configured_available: false,
      unavailable_reason: 'price_not_set',
    })
    assert.deepEqual(arrangementStatus(a), {
      label: 'Needs attention', tone: 'attention',
    })
  })

  it('an invalid schedule needs attention and is not estimated', () => {
    const a = arrangement({
      schedule_type: 'recurring_installments',
      installment_amount_cents: null,
      installment_count: null,
      total_amount_cents: null,
      available_for_new_purchase: false,
      unavailable_reason: 'schedule_invalid',
    })
    assert.equal(arrangementStatus(a).label, 'Needs attention')
    assert.match(arrangementExplanation(a, 'pathway')!, /missing something/)
    assert.ok(!arrangementPaymentLine(a).includes('$'))
  })
})

describe('configured and purchasable are kept apart', () => {
  it('a legacy-restricted direct price is pending, not broken', () => {
    // pricing_mode='payment_options'. The creator did nothing wrong
    // and can do nothing about it, so it must not read as a mistake.
    const a = arrangement({
      source: 'direct',
      total_amount_cents: 4900,
      available_for_new_purchase: false,
      configured_available: true,
      blocked_by_platform: true,
      unavailable_reason: 'pathway_requires_payment_option',
    })
    assert.deepEqual(arrangementStatus(a), {
      label: 'Not purchasable yet', tone: 'pending',
    })
    assert.notEqual(arrangementStatus(a).tone, 'attention')
    const copy = arrangementExplanation(a, 'pathway')!
    assert.match(copy, /sells through Payment Options/)
    // And the price stays visible.
    assert.equal(arrangementPaymentLine(a), '$49 once')
  })

  it('switched-off ticket sales are pending, in the editors own words', () => {
    const a = arrangement({
      source: 'direct',
      total_amount_cents: 300000,
      available_for_new_purchase: false,
      configured_available: true,
      blocked_by_platform: true,
      unavailable_reason: 'gathering_sales_disabled',
    })
    assert.equal(arrangementStatus(a).tone, 'pending')
    assert.equal(arrangementPaymentLine(a), '$3000 once')
    const copy = arrangementExplanation(a, 'gathering')!
    // Same fact, same wording as the ticket-price field already uses.
    assert.match(copy, /switched off on this environment/)
    assert.match(copy, /cannot be bought yet/)
  })

  it('an experience that is not live says so for its own kind', () => {
    const a = arrangement({
      source: 'direct',
      available_for_new_purchase: false,
      unavailable_reason: 'experience_unavailable',
    })
    assert.match(arrangementExplanation(a, 'pathway')!, /Pathway is not active/)
    assert.match(arrangementExplanation(a, 'gathering')!, /not published/)
  })
})

describe('empty states say what is true', () => {
  it('a public Pathway has nothing to purchase, and that is fine', () => {
    const { text, isGap } = accessExplanation(
      preview({ access_type: 'free', arrangements: [] }),
    )
    assert.match(text, /nothing to purchase/)
    assert.equal(isGap, false)
  })

  it('a members-only Pathway likewise', () => {
    const { text, isGap } = accessExplanation(
      preview({ access_type: 'included' }),
    )
    assert.match(text, /included for members/)
    assert.equal(isGap, false)
  })

  it('but Payment Option access with no Option is a real gap', () => {
    const { text, isGap } = accessExplanation(
      preview({ access_type: 'included_with_offer' }),
    )
    assert.equal(isGap, true)
    assert.match(text, /no one can reach it/)
  })

  it('a legacy subscription Pathway is retired, not unconfigured', () => {
    // Nothing sells a per-Pathway subscription, so the resolver emits
    // no arrangement. "Nothing is set up" would be the wrong reading:
    // something is set up and it is retired.
    const { text, isGap } = accessExplanation(
      preview({ access_type: 'subscription' }),
    )
    assert.equal(isGap, true)
    assert.match(text, /no longer sold/)
    assert.match(text, /Payment Options/)
  })

  it('a ticketed Gathering with no price is a real gap', () => {
    const { text, isGap } = accessExplanation(
      preview({ experience_kind: 'gathering', access_type: 'paid_separately' }),
    )
    assert.equal(isGap, true)
    assert.match(text, /no ticket price is set/)
  })

  it('a Series-pass Gathering points at the pass, not at itself', () => {
    const { text, isGap } = accessExplanation(
      preview({
        experience_kind: 'gathering', access_type: 'included_with_series',
      }),
    )
    assert.equal(isGap, false)
    assert.match(text, /buy the pass/)
  })

  it('an invitation-only Gathering is not a purchase at all', () => {
    const { text, isGap } = accessExplanation(
      preview({
        experience_kind: 'gathering', access_type: 'invitation_only',
      }),
    )
    assert.equal(isGap, false)
    assert.match(text, /nothing to purchase/)
  })
})

describe('bundles describe themselves without internal vocabulary', () => {
  it('names the other experiences, not their kinds', () => {
    const p = preview({
      title: 'Foundations',
      arrangements: [
        arrangement({
          is_bundle: true,
          included: [
            { kind: 'pathway', title: 'Foundations' },
            { kind: 'pathway', title: 'Deepening' },
            { kind: 'event_series', title: 'Term 4' },
          ],
        }),
      ],
    })
    const group = groupByOption(p)[0]
    const extras = alsoIncluded(group, p)
    // The Pathway being viewed is not "also included" in its own bundle.
    assert.deepEqual(extras.map((e) => e.title), ['Deepening', 'Term 4'])
  })

  it('labels a kind in product language when a title is missing', () => {
    assert.equal(includedKindLabel('event_series'), 'Gathering Series')
    assert.equal(includedKindLabel('pathway'), 'Pathway')
    assert.equal(includedKindLabel('offering'), 'Offering')
    // Never the raw value.
    assert.ok(!includedKindLabel('event_series').includes('_'))
    // An unknown kind still reads as English.
    assert.equal(includedKindLabel('mystery'), 'Experience')
  })
})

// ---------------------------------------------------------------------------
// Cross-boundary contract
// ---------------------------------------------------------------------------

describe('every reason the backend can emit has copy here', () => {
  /**
   * The failure this prevents is specific: the backend adds a reason,
   * the frontend falls through to its generic sentence, and a creator
   * is told "members cannot purchase this right now" when the real
   * answer was "publish the schedule". Asserted against the Python
   * constants rather than a hand-maintained list, so the two cannot
   * drift.
   */
  const BACKEND = join(process.cwd(), '..', 'backend', 'app', 'services')
  const FILES = ['purchase_arrangements.py', 'creator_purchase_preview.py']

  function backendReasons(): string[] {
    const found: string[] = []
    for (const file of FILES) {
      const path = join(BACKEND, file)
      assert.ok(existsSync(path), `missing ${path}`)
      const src = readFileSync(path, 'utf8')
      for (const m of src.matchAll(/^REASON_[A-Z_]+ = "([a-z_]+)"$/gm)) {
        found.push(m[1])
      }
    }
    return found
  }

  it('finds the reason constants', () => {
    // Guards the regex itself: a silent zero would make the test below
    // pass vacuously.
    assert.ok(backendReasons().length >= 12, backendReasons().join(','))
  })

  it('words each one specifically', () => {
    const generic = arrangementExplanation(
      arrangement({
        available_for_new_purchase: false,
        unavailable_reason: 'a_reason_that_does_not_exist',
      }),
      'pathway',
    )
    for (const reason of backendReasons()) {
      for (const kind of ['pathway', 'gathering'] as const) {
        const copy = arrangementExplanation(
          arrangement({
            available_for_new_purchase: false,
            unavailable_reason: reason,
          }),
          kind,
        )
        assert.ok(copy, `${reason}: no copy`)
        assert.notEqual(copy, generic, `${reason}: fell through to the generic sentence`)
      }
    }
  })

  it('and badges each one as something other than Available', () => {
    for (const reason of backendReasons()) {
      const status = arrangementStatus(
        arrangement({
          available_for_new_purchase: false,
          unavailable_reason: reason,
        }),
      )
      assert.notEqual(status.label, 'Available', reason)
      assert.notEqual(status.tone, 'available', reason)
    }
  })
})
