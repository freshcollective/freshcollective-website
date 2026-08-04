import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getDevOnlyDetail,
  getUnavailableCopy,
} from './checkoutUnavailable.ts'

// ---------------------------------------------------------------------------
// User-facing copy — must never expose backend / operator text
// ---------------------------------------------------------------------------

test('getUnavailableCopy — heading is calm and environmental, not accusatory', () => {
  const { heading } = getUnavailableCopy()
  assert.equal(
    heading,
    "Payments aren't available in this environment yet.",
  )
})

test('getUnavailableCopy — body explains no charge occurred', () => {
  const { body } = getUnavailableCopy()
  assert.match(body, /No payment has been created/i)
  assert.match(body, /nothing has been charged/i)
})

test('getUnavailableCopy — copy never mentions env vars, secrets, or operator instructions', () => {
  const { heading, body } = getUnavailableCopy()
  const combined = `${heading}\n${body}`
  const forbidden = [
    /STRIPE_/,           // any Stripe env-var prefix
    /_PRICE_ID/,          // Price-ID identifiers
    /_SECRET/,            // secret-key hints
    /env(?:ironment)?\s+variable/i,
    /operator/i,
    /add\s+the/i,         // "add the ... to your .env"
    /\.env/i,
    /SDK/,
  ]
  for (const rule of forbidden) {
    assert.doesNotMatch(combined, rule, `Copy leaked pattern ${rule}`)
  }
})

// ---------------------------------------------------------------------------
// Dev-only detail — hidden outside development, hidden without a var
// ---------------------------------------------------------------------------

test('getDevOnlyDetail — returns null in production, even when a var name is supplied', () => {
  assert.equal(
    getDevOnlyDetail('STRIPE_PRICE_ID_CREATOR', 'production'),
    null,
  )
})

test('getDevOnlyDetail — returns "Missing X" in development', () => {
  assert.equal(
    getDevOnlyDetail('STRIPE_PRICE_ID_CREATOR', 'development'),
    'Missing STRIPE_PRICE_ID_CREATOR',
  )
})

test('getDevOnlyDetail — returns null when the backend did not supply a var name', () => {
  assert.equal(getDevOnlyDetail(null, 'development'), null)
  assert.equal(getDevOnlyDetail(undefined, 'development'), null)
  assert.equal(getDevOnlyDetail('', 'development'), null)
})

test('getDevOnlyDetail — treats "test" and other non-production envs like development', () => {
  assert.equal(
    getDevOnlyDetail('STRIPE_PRICE_ID_PRO', 'test'),
    'Missing STRIPE_PRICE_ID_PRO',
  )
  assert.equal(
    getDevOnlyDetail('STRIPE_PRICE_ID_PRO', undefined),
    'Missing STRIPE_PRICE_ID_PRO',
  )
})
