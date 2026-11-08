/**
 * Stage 4 — the member's side of a discount.
 *
 * Two things are worth pinning here, and neither is cosmetic.
 *
 * The browser must never compute money. A discounted commitment rarely
 * divides into equal cents, so a client that divided a total by a count
 * would show a schedule the member is not actually charged — and the
 * figures it showed would have to agree with a separate server
 * calculation forever. Every amount rendered comes from the server in
 * the same response that declared the code valid.
 *
 * And the schedule must be named accurately. "3 payments of A$43.33" is
 * a small lie about the last one; rounding the lot up to A$43.34 is a
 * larger one about all of them. §7 is explicit that slightly different
 * instalments are displayed as they are.
 */

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  describeApplied,
  describeSchedule,
  targetBody,
  type DiscountPreview,
} from './discountPreview.ts'

// The brief's §7 example, as the server would answer it.
const UNEVEN_PLAN: DiscountPreview = {
  valid: true,
  code: 'FAMILY50',
  original_amount_cents: 15_000,
  discount_amount_cents: 2_000,
  final_amount_cents: 13_000,
  currency: 'AUD',
  payment_mode: 'plan',
  installment_count: 3,
  installment_amount_cents: 4_333,
  final_installment_amount_cents: 4_334,
}

// §6's example — exact division, which is the common real case.
const EVEN_PLAN: DiscountPreview = {
  valid: true,
  code: 'WELCOME20',
  original_amount_cents: 20_000,
  discount_amount_cents: 4_000,
  final_amount_cents: 16_000,
  currency: 'AUD',
  payment_mode: 'plan',
  installment_count: 4,
  installment_amount_cents: 4_000,
  final_installment_amount_cents: 4_000,
}

const SINGLE: DiscountPreview = {
  valid: true,
  code: 'WELCOME20',
  original_amount_cents: 10_000,
  discount_amount_cents: 2_000,
  final_amount_cents: 8_000,
  currency: 'AUD',
  payment_mode: 'single',
}


describe('describing a discounted payment schedule', () => {
  test('an uneven plan names the final payment separately', () => {
    // §7, verbatim: A$43.33, A$43.33, A$43.34 — A$130 total.
    const shown = describeSchedule(UNEVEN_PLAN)

    assert.deepEqual(shown, {
      line: '2 payments of A$43.33, then A$43.34',
      total: 'A$130',
      isEven: false,
    })
  })

  test('an even plan reads as one repeated amount', () => {
    const shown = describeSchedule(EVEN_PLAN)

    assert.deepEqual(shown, {
      line: '4 payments of A$40',
      total: 'A$160',
      isEven: true,
    })
  })

  test('a two-payment uneven plan does not say "1 payments"', () => {
    const shown = describeSchedule({
      ...UNEVEN_PLAN, installment_count: 2,
      installment_amount_cents: 5_000,
      final_installment_amount_cents: 5_001,
      final_amount_cents: 10_001,
    })

    assert.equal(shown?.line, '1 payment of A$50, then A$50.01')
  })

  test('a single-payment plan is still described', () => {
    const shown = describeSchedule({
      ...EVEN_PLAN, installment_count: 1,
      installment_amount_cents: 16_000,
      final_installment_amount_cents: 16_000,
    })

    assert.equal(shown?.line, '1 payment of A$160')
  })

  test('a pay-in-full preview has no schedule to describe', () => {
    // The total is the whole answer there, and inventing a one-line
    // schedule for it would say the same thing twice.
    assert.equal(describeSchedule(SINGLE), null)
  })

  test('a rejected code has no schedule', () => {
    assert.equal(describeSchedule({
      valid: false, code: 'X', payment_mode: 'plan',
    }), null)
  })

  test('a plan preview missing its figures renders nothing at all', () => {
    // Half a schedule is worse than none: "2 payments of , then "
    // reaches the member as a broken promise about their money.
    for (const missing of [
      'installment_count', 'installment_amount_cents',
      'final_installment_amount_cents', 'currency', 'final_amount_cents',
    ] as const) {
      const partial = { ...UNEVEN_PLAN, [missing]: null }
      assert.equal(describeSchedule(partial), null, missing)
    }
  })

  test('the currency is the server’s, never a literal dollar sign', () => {
    const shown = describeSchedule({ ...EVEN_PLAN, currency: 'USD' })

    assert.equal(shown?.line, '4 payments of US$40')
    assert.equal(shown?.total, 'US$160')
  })

  test('the three headline figures still describe the whole commitment', () => {
    // On a plan the discount applied to the commitment, so "you save"
    // is the whole saving — not a share of one payment.
    const shown = describeApplied(UNEVEN_PLAN)

    assert.deepEqual(shown, {
      original: 'A$150',
      saving: 'A$20',
      final: 'A$130',
    })
  })
})


/**
 * Every ``JSON.stringify(...)`` argument list in a source file.
 *
 * Parenthesis-matched rather than regex-matched: a request body is a
 * nested object literal, and the first `)` in it is usually part of
 * something else.
 */
function requestBodies(source: string): string[] {
  const found: string[] = []
  const marker = 'JSON.stringify('
  let from = 0
  for (;;) {
    const at = source.indexOf(marker, from)
    if (at === -1) return found
    let depth = 1
    let i = at + marker.length
    for (; i < source.length && depth > 0; i += 1) {
      if (source[i] === '(') depth += 1
      else if (source[i] === ')') depth -= 1
    }
    found.push(source.slice(at + marker.length, i - 1))
    from = i
  }
}


describe('what the browser sends', () => {
  test('a Payment Option names its option and schedule', () => {
    assert.deepEqual(
      targetBody({
        kind: 'payment_option',
        paymentOptionId: 'po_1',
        paymentOptionScheduleId: 'pos_1',
      }),
      { payment_option_id: 'po_1', payment_option_schedule_id: 'pos_1' },
    )
  })

  test('a direct Pathway names the experience and nothing else', () => {
    // No Payment Option, deliberately. That absence is what keeps a code
    // scoped to one Option off a standalone purchase of something that
    // Option includes — the server refuses it on exactly that basis.
    assert.deepEqual(
      targetBody({ kind: 'pathway', targetId: 'pw_1' }),
      { direct_kind: 'pathway', direct_id: 'pw_1' },
    )
  })

  test('a direct Gathering names the Gathering', () => {
    assert.deepEqual(
      targetBody({ kind: 'gathering', targetId: 'ev_1' }),
      { direct_kind: 'gathering', direct_id: 'ev_1' },
    )
  })

  test('an Offering names its slugs, not a direct target', () => {
    // An Offering purchase genuinely IS a Payment Option purchase — the
    // server resolves the Option behind the slugs and prices it as one.
    // Sending it as ``direct_kind`` would make the server refuse a code
    // the creator scoped to that very Option.
    assert.deepEqual(
      targetBody({
        kind: 'offering', spaceSlug: 'moonlit-circle', offeringSlug: 'ritual-kit',
      }),
      { offering_space_slug: 'moonlit-circle', offering_slug: 'ritual-kit' },
    )
  })

  test('no amount is ever sent back', () => {
    // The code is all that goes to checkout. A price in the request is a
    // price the member can edit.
    //
    // Scoped to the *arguments* of each ``JSON.stringify`` call, by
    // matching its parentheses. A blunter check — everything after the
    // call — swept up the response interface and the schedule formatter
    // below it, which read those field names precisely because the
    // server sends them. Ban the use, not the word.
    const sources = [
      'src/lib/discountPreview.ts',
      'src/components/checkout/DiscountCodeField.tsx',
      'src/components/commerce/PurchaseScheduleButton.tsx',
      'src/components/checkout/CheckoutButton.tsx',
      'src/components/spaces/GatheringTicketPurchaseClient.tsx',
    ]
    for (const path of sources) {
      for (const body of requestBodies(readFileSync(path, 'utf8'))) {
        for (const forbidden of [
          'final_amount_cents', 'discount_amount_cents',
          'original_amount_cents', 'installment_amount_cents',
        ]) {
          assert.ok(
            !body.includes(forbidden),
            `${path} must not send ${forbidden} — found in: ${body}`,
          )
        }
      }
    }
  })
})


describe('every purchase door offers the same field', () => {
  // §9 asks for code entry wherever a supported experience can be
  // bought, and §16 for no separate interface per type. Checked by
  // source because the property is "this component is reached from all
  // of these places", which no single render can demonstrate.
  const DOORS: Array<[string, string]> = [
    ['direct Pathway', 'src/components/commerce/PathwayWaysToJoin.tsx'],
    ['Payment Option', 'src/components/commerce/PurchaseScheduleButton.tsx'],
    ['Gathering ticket', 'src/components/spaces/GatheringTicketPurchaseClient.tsx'],
    ['Offering', 'src/components/offerings/AcquireOffering.tsx'],
  ]

  for (const [name, path] of DOORS) {
    test(`the ${name} door uses DiscountCodeField`, () => {
      const source = readFileSync(path, 'utf8')

      assert.match(source, /import DiscountCodeField from/)
      assert.match(source, /<DiscountCodeField/)
      // Gated on the server's answer, never on a hardcoded guess.
      assert.match(source, /discountCodesEnabled/)
    })
  }

  test('the Series and joining doors reach it through ScheduleChoice', () => {
    // Both are Payment Option purchases, so they get the field by
    // threading the flag rather than by mounting a second one.
    for (const path of [
      'src/app/spaces/[slug]/gathering-series/[series-slug]/SeriesSidebar.tsx',
      'src/app/spaces/[slug]/about/JoiningDoors.tsx',
    ]) {
      const source = readFileSync(path, 'utf8')
      assert.match(source, /discountCodesEnabled/, path)
      assert.ok(!source.includes('<DiscountCodeField'), path)
    }
  })

  test('no door hardcodes the flag on', () => {
    // The whole safety case for shipping this dark is that the browser
    // cannot turn it on.
    for (const [, path] of DOORS) {
      const source = readFileSync(path, 'utf8')
      assert.ok(
        !/discountCodesEnabled\s*=\s*true/.test(source),
        `${path} must not default the flag on`,
      )
    }
  })
})
