import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as ts from 'typescript'

import {
  describeApplied,
  normaliseCodeInput,
  stateFromPreview,
  type DiscountPreview,
} from './discountPreview.ts'

// EMBODY Activate, as verified in production.
const APPLIED: DiscountPreview = {
  valid: true,
  code: 'FAMILY50',
  original_amount_cents: 30600,
  discount_amount_cents: 15300,
  final_amount_cents: 15300,
  currency: 'AUD',
}

describe('reading the server’s verdict', () => {
  test('a valid preview renders the three figures it was given', () => {
    const shown = describeApplied(APPLIED)

    assert.deepEqual(shown, {
      original: 'A$306',
      saving: 'A$153',
      final: 'A$153',
    })
  })

  test('a rejection keeps the server’s own words', () => {
    // "That code expired on Sunday" is worth more to a member than
    // "invalid code", and only the server knows which it is.
    const state = stateFromPreview({
      valid: false, code: 'FAMILY50',
      reason: 'expired', message: 'That code has expired.',
    })

    assert.equal(state.status, 'rejected')
    assert.equal(state.status === 'rejected' && state.message, 'That code has expired.')
  })

  test('a rejection with no message still says something useful', () => {
    const state = stateFromPreview({ valid: false, code: 'X' })

    assert.equal(state.status, 'rejected')
    assert.match(state.status === 'rejected' ? state.message : '', /cannot be used/)
  })

  test('a valid verdict missing its figures is treated as unusable', () => {
    // Rendering "you save " with a blank is worse than not offering the
    // code at all, so a half-formed response is refused outright.
    assert.equal(describeApplied({ valid: true, code: 'X' }), null)
    assert.equal(stateFromPreview({ valid: true, code: 'X' }).status, 'rejected')
  })

  test('an invalid verdict has nothing to render', () => {
    assert.equal(describeApplied({ valid: false, code: 'X', reason: 'not_found' }), null)
  })
})

describe('what gets typed', () => {
  for (const typed of ['family50', '  FAMILY50  ', 'Family50', '\tfamily50\n']) {
    test(`"${typed.trim()}" normalises to the stored form`, () => {
      assert.equal(normaliseCodeInput(typed), 'FAMILY50')
    })
  }

  test('an empty box normalises to nothing, not to a code', () => {
    assert.equal(normaliseCodeInput('   '), '')
  })
})

// ---------------------------------------------------------------------------
// The rule, enforced against the source rather than trusted
// ---------------------------------------------------------------------------

describe('the browser does not price anything', () => {
  const SOURCES = [
    'src/lib/discountPreview.ts',
    'src/components/checkout/DiscountCodeField.tsx',
    'src/components/commerce/PurchaseScheduleButton.tsx',
  ]

  function parse(file: string) {
    return ts.createSourceFile(
      file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true,
    )
  }

  function walk(node: ts.Node, visit: (n: ts.Node) => void) {
    visit(node)
    node.forEachChild((child) => walk(child, visit))
  }

  test('no arithmetic is performed on any amount field', () => {
    // Checks the AST, not the text, so a comment explaining the rule
    // cannot fail the test that enforces it.
    const AMOUNT = /amount_cents|_cents$|discountCents|finalCents/
    const ARITHMETIC = new Set([
      ts.SyntaxKind.MinusToken,
      ts.SyntaxKind.AsteriskToken,
      ts.SyntaxKind.SlashToken,
      ts.SyntaxKind.PercentToken,
    ])
    const offences: string[] = []

    for (const file of SOURCES) {
      walk(parse(file), (node) => {
        if (!ts.isBinaryExpression(node)) return
        if (!ARITHMETIC.has(node.operatorToken.kind)) return
        const text = node.getText()
        if (AMOUNT.test(text)) offences.push(`${file}: ${text}`)
      })
    }

    assert.deepEqual(offences, [], `amounts must come from the server:\n${offences.join('\n')}`)
  })

  test('checkout sends a code and never an amount', () => {
    const source = readFileSync('src/components/commerce/PurchaseScheduleButton.tsx', 'utf8')
    const body = source.slice(source.indexOf('JSON.stringify'))
    const sent = body.slice(0, body.indexOf('})'))

    assert.match(sent, /discount_code/)
    for (const forbidden of [
      'discount_amount_cents', 'final_amount_cents', 'original_amount_cents',
    ]) {
      assert.ok(!sent.includes(forbidden), `checkout must not send ${forbidden}`)
    }
  })
})


// ---------------------------------------------------------------------------
// Stage 4 scope: every supported purchase, including payment plans
// ---------------------------------------------------------------------------

describe('where the code field appears', () => {
  const BUTTON = 'src/components/commerce/PurchaseScheduleButton.tsx'

  test('the field is gated on the server\u2019s answer, not the schedule type', () => {
    // Stage 4 replaced the v1 rule ("pay-in-full only") with the Stage 4
    // flag, resolved server-side. Pinned against the source because the
    // alternatives are both wrong in ways no input can demonstrate:
    // gating on "does this need a confirm dialog?" is false for a plan
    // with incomplete instalment metadata, and gating on nothing at all
    // offers a code box whose every submission the server refuses while
    // the flag is off.
    const source = readFileSync(BUTTON, 'utf8')

    assert.match(source, /const canUseCode = discountCodesEnabled && Boolean\(paymentOptionScheduleId\)/)
    assert.match(source, /\{canUseCode && \(\s*<DiscountCodeField/)
    assert.ok(!/\{!needsConfirm && \(\s*<DiscountCodeField/.test(source),
      'the field must not be gated on the confirm-dialog flag')
    assert.ok(!source.includes("schedule_type === 'pay_in_full'"),
      'the v1 pay-in-full gate must be gone, not merely bypassed')
  })

  test('the flag defaults off, so an un-taught surface shows no code box', () => {
    // A surface that has not been given ``discountCodesEnabled`` must
    // show nothing rather than a box that always fails. Default-on would
    // make every caller that forgets the prop a broken checkout.
    const source = readFileSync(BUTTON, 'utf8')

    assert.match(source, /discountCodesEnabled = false/)
  })

  test('one field serves every purchase type', () => {
    // §9 asks for this directly: no separate discount interface per
    // experience type. What varies is the target handed to the field.
    const field = readFileSync(
      'src/components/checkout/DiscountCodeField.tsx', 'utf8')

    assert.match(field, /target: DiscountTarget/)
    assert.match(field, /previewDiscount\(\{ code, target, signal/)
  })
})


describe('the creator form describes what a code covers', () => {
  const FORM = 'src/app/creator-studio/discount-codes/DiscountCodesClient.tsx'

  test('the pay-in-full-only restriction is gone', () => {
    // It was true before Stage 4 and is now the opposite of true, so
    // leaving it would misdescribe the creator\u2019s own code.
    const form = readFileSync(FORM, 'utf8')

    assert.ok(!form.includes('apply to pay-in-full purchases only'))
  })

  test('payment plans are named, and so is how the discount is spread', () => {
    const form = readFileSync(FORM, 'utf8')

    assert.match(form, /payment plans/)
    assert.match(form, /spread across all scheduled payments/)
  })

  test('no creator copy promises a code covers everything sold', () => {
    // "on everything you sell" overpromises even now: a code scoped to
    // one Payment Option covers exactly that Option, and a
    // Collective-wide one still only reaches *eligible* purchases.
    const form = readFileSync(FORM, 'utf8')

    assert.ok(!form.includes('everything you sell'))
  })
})
