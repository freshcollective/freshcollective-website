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
// v1 scope: pay-in-full only
// ---------------------------------------------------------------------------

describe('the code field belongs to pay-in-full purchases only', () => {
  const BUTTON = 'src/components/commerce/PurchaseScheduleButton.tsx'

  test('the field is gated on the schedule being pay_in_full', () => {
    // Pinned against the source because the alternative — gating on
    // "does this need a confirm dialog?" — is false for a plan with
    // incomplete instalment metadata and false again for a caller that
    // omits the schedule. Either would offer a code box on a purchase
    // the server refuses codes for.
    const source = readFileSync(BUTTON, 'utf8')

    assert.match(source, /const isPayInFull = schedule\?\.schedule_type === 'pay_in_full'/)
    assert.match(source, /\{isPayInFull && \(\s*<DiscountCodeField/)
    assert.ok(!/\{!needsConfirm && \(\s*<DiscountCodeField/.test(source),
      'the field must not be gated on the confirm-dialog flag')
  })

  test('the creator form says which purchases a code applies to', () => {
    const form = readFileSync(
      'src/app/creator-studio/discount-codes/DiscountCodesClient.tsx', 'utf8')

    assert.match(form, /apply to pay-in-full purchases only/)
  })

  test('no creator copy promises a code covers everything sold', () => {
    // "on everything you sell" was true before payment plans were
    // excluded, and would now be a promise the checkout does not keep.
    const form = readFileSync(
      'src/app/creator-studio/discount-codes/DiscountCodesClient.tsx', 'utf8')

    assert.ok(!form.includes('everything you sell'))
  })
})
