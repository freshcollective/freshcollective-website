import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Admin Payments must distinguish the two axes.
 *
 * ``fulfilment_status='blocked'`` was written by five handlers and read
 * by nothing, so a purchase we collected for and failed to deliver was
 * discoverable only in the logs. These assertions pin the three things
 * that fix it: the status is displayed, it is filterable, and a blocked
 * row carries the Stripe handle an operator follows it up with.
 *
 * Source-level, because this runner has no DOM.
 */

const SRC = dirname(fileURLToPath(import.meta.url))
const page = readFileSync(
  join(SRC, '..', 'app', 'admin', 'payments', 'page.tsx'), 'utf8',
)

describe('payment and fulfilment are presented as separate axes', () => {
  test('the table has both columns, named distinctly', () => {
    assert.match(page, /'Date', 'Type', 'Payment', 'Fulfilment'/)
  })

  test('the payment column is no longer called just "Status"', () => {
    // "Payment: Successful / Fulfilment: Blocked" only reads if the
    // first column stops claiming the generic name.
    assert.ok(!/'Date', 'Type', 'Status'/.test(page))
  })

  test('each row renders both', () => {
    assert.match(page, /StatusPill hue=\{STATUS_HUE\[row\.status\]/)
    assert.match(page, /<FulfilmentCell row=\{row\}/)
  })

  test('the mobile card renders both too', () => {
    // Otherwise a blocked fulfilment would be desktop-only.
    const mobile = page.slice(page.indexOf('function TransactionMobileRow'))
    assert.match(mobile, /STATUS_HUE\[row\.status\]/)
    assert.match(mobile, /<FulfilmentCell row=\{row\}/)
  })
})

describe('blocked is visually the one needing attention', () => {
  test('it is coral, like the other action-required states', () => {
    const hues = page.slice(
      page.indexOf('const FULFILMENT_HUE'),
      page.indexOf('const FULFILMENT_OPTIONS'),
    )
    assert.match(hues, /blocked: 'coral'/)
    assert.match(hues, /applied: 'teal'/)
    assert.match(hues, /pending: 'gold'/)
  })

  test('it uses the existing badge primitive', () => {
    const cell = page.slice(
      page.indexOf('function FulfilmentCell'),
      page.indexOf('function StatusPill'),
    )
    assert.match(cell, /<StatusPill hue=\{FULFILMENT_HUE/)
  })
})

describe('filtering for blocked fulfilments', () => {
  test('the filter exists and is labelled', () => {
    assert.match(page, /label="Fulfilment" value=\{fulfilment\}/)
  })

  test('blocked is offered first and says why it matters', () => {
    const opts = page.slice(
      page.indexOf('const FULFILMENT_OPTIONS'),
      page.indexOf('const PAYOUT_HUE'),
    )
    assert.match(opts, /\['blocked', 'Blocked — needs attention'\]/)
    // Immediately after "all", so it is the first real choice.
    assert.ok(opts.indexOf("'blocked'") < opts.indexOf("'pending'"))
  })

  test('the filter is actually applied to the rows', () => {
    assert.match(
      page,
      /if \(fulfilment !== 'all' && r\.fulfilment_status !== fulfilment\) return false/,
    )
  })

  test('it participates in the memo dependencies', () => {
    assert.match(page, /\[rows, search, status, fulfilment, type, payout, creator\]/)
  })

  test('it counts towards "clear filters"', () => {
    assert.match(page, /fulfilment !== 'all'/)
  })
})

describe('the Stripe reference for follow-up', () => {
  test('it comes from the payments endpoint, not the ledger', () => {
    // The ledger deliberately exposes no provider IDs — it is a
    // reporting surface. The admin payments endpoint is the one
    // designed to carry them, and is admin-gated the same way.
    assert.match(
      page,
      /\/api\/admin\/payments\?fulfilment_status=blocked/,
    )
  })

  test('the ledger row type claims no provider IDs', () => {
    const rowType = page.slice(
      page.indexOf('interface LedgerRow'),
      page.indexOf('const PERIOD_OPTIONS') > 0
        ? page.indexOf('const PERIOD_OPTIONS')
        : page.indexOf('const STATUS_HUE'),
    )
    assert.ok(!/provider_payment_intent_id/.test(rowType))
    assert.ok(!/provider_checkout_session_id/.test(rowType))
  })

  test('the lookup is not narrowed by the selected period', () => {
    // An unfulfilled purchase needs chasing whenever it happened.
    const fetchLine = page.slice(
      page.indexOf('/api/admin/payments?fulfilment_status=blocked') - 200,
      page.indexOf('/api/admin/payments?fulfilment_status=blocked') + 120,
    )
    assert.ok(!/period=\$\{period\}/.test(fetchLine))
  })

  test('the reference is shown only on a blocked row', () => {
    const cell = page.slice(
      page.indexOf('function FulfilmentCell'),
      page.indexOf('function StatusPill'),
    )
    assert.match(cell, /blocked && detail\?\.ref &&/)
    assert.match(cell, /const blocked = row\.fulfilment_status === 'blocked'/)
  })

  test('a blocked row with no reference says so rather than rendering blank', () => {
    const cell = page.slice(
      page.indexOf('function FulfilmentCell'),
      page.indexOf('function StatusPill'),
    )
    assert.match(cell, /No Stripe reference/)
  })

  test('it falls back from payment intent to checkout session', () => {
    assert.match(
      page,
      /provider_payment_intent_id \?\? b\.provider_checkout_session_id/,
    )
  })
})

describe('no new payment actions were added', () => {
  const cell = page.slice(
    page.indexOf('function FulfilmentCell'),
    page.indexOf('function StatusPill'),
  )

  test('the fulfilment cell has no buttons or handlers', () => {
    assert.ok(!/<button/i.test(cell))
    assert.ok(!/onClick/.test(cell))
  })

  test('nothing offers a refund or a replay', () => {
    // Bans the action, not the word: the tooltips name a replay
    // deliberately, because telling the admin which fix applies is the
    // point of the classification. What must not exist is a control.
    const code = cell
      .replace(/'[^'\n]*'/g, "''")
      .replace(/"[^"\n]*"/g, '""')
      .replace(/\/\*[\s\S]*?\*\//g, '')
    assert.ok(!/<button/i.test(code))
    assert.ok(!/onClick/.test(code))
    assert.ok(!/fetch\(/.test(code))
  })
})

describe('the blocked reason distinguishes temporary from permanent', () => {
  test('a classifier exists rather than raw strings on screen', () => {
    assert.match(page, /function classifyBlock/)
  })

  test('ineligibility is marked as needing a decision', () => {
    const fn = page.slice(
      page.indexOf('function classifyBlock'),
      page.indexOf('const PAYOUT_HUE'),
    )
    assert.match(fn, /membership_ineligible/)
    assert.match(fn, /needsDecision: true/)
  })

  test('a data fault is not marked as needing a decision', () => {
    const fn = page.slice(
      page.indexOf('function classifyBlock'),
      page.indexOf('const PAYOUT_HUE'),
    )
    // The fall-through case: anything that is not ineligibility.
    assert.match(fn, /needsDecision: false/)
  })

  test('an unrecorded reason says so rather than guessing', () => {
    const fn = page.slice(
      page.indexOf('function classifyBlock'),
      page.indexOf('const PAYOUT_HUE'),
    )
    assert.match(fn, /Reason not recorded/)
  })

  test('the two classes are visually distinct', () => {
    const cell = page.slice(
      page.indexOf('function FulfilmentCell'),
      page.indexOf('function StatusPill'),
    )
    assert.match(cell, /classified\.needsDecision \? WM_HUE\.coral\.text/)
  })

  test('each class explains what to do', () => {
    const cell = page.slice(
      page.indexOf('function FulfilmentCell'),
      page.indexOf('function StatusPill'),
    )
    assert.match(cell, /a replay will not fix this/i)
    assert.match(cell, /re-send the Stripe event/i)
  })

  test('the reason and plan come from the payments endpoint', () => {
    assert.match(page, /fulfilment_blocked_reason: string \| null/)
    assert.match(page, /purchase_plan_id: string \| null/)
  })

  test('a blocked instalment shows its plan', () => {
    const cell = page.slice(
      page.indexOf('function FulfilmentCell'),
      page.indexOf('function StatusPill'),
    )
    assert.match(cell, /detail\?\.planId/)
    assert.match(cell, /plan \{detail\.planId\}/)
  })

  test('still no actions on the row', () => {
    const cell = page.slice(
      page.indexOf('function FulfilmentCell'),
      page.indexOf('function StatusPill'),
    )
    assert.ok(!/<button/i.test(cell))
    assert.ok(!/onClick/.test(cell))
  })
})
