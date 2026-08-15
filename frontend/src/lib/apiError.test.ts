/**
 * Unit tests for the FastAPI/fetch error extractor.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping:
 *
 *   node --experimental-strip-types --test src/lib/apiError.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path
import { extractApiErrorMessage } from './apiError.ts'


describe('extractApiErrorMessage — the [object Object] regression', () => {
  test('never returns "[object Object]" for a dict error body', () => {
    // The exact FIP1 validator shape that produced [object Object]
    // in the browser.
    const body = {
      detail: {
        message: 'Payment plan schedule is not valid for checkout.',
        errors: [
          'stripe_interval and stripe_interval_count are required for recurring_installments.',
        ],
      },
    }
    const msg = extractApiErrorMessage(body)
    assert.notEqual(msg, '[object Object]')
    assert.ok(msg.includes('Payment plan schedule'))
    assert.ok(msg.includes('stripe_interval'))
  })

  test('an Error whose message was String(dict) — falls back to fallback', () => {
    // Simulate the historical bug: someone did new Error(String(obj))
    // and the Error's .message is literally "[object Object]".
    const err = new Error('[object Object]')
    assert.equal(
      extractApiErrorMessage(err, { fallback: 'Save failed.' }),
      'Save failed.',
    )
  })
})


describe('extractApiErrorMessage — FastAPI shapes', () => {
  test('plain-string detail', () => {
    assert.equal(
      extractApiErrorMessage({ detail: 'Payment schedule not found.' }),
      'Payment schedule not found.',
    )
  })

  test('FIP1 structured detail with message + errors', () => {
    const body = {
      detail: {
        message: 'Invalid recurring_installments schedule.',
        errors: [
          'installment_count must be at least 2.',
          'currency must be a 3-letter ISO 4217 code.',
        ],
      },
    }
    const msg = extractApiErrorMessage(body)
    assert.ok(msg.startsWith('Invalid recurring_installments schedule.'))
    assert.ok(msg.includes('installment_count'))
    assert.ok(msg.includes('currency'))
  })

  test('Pydantic validation list', () => {
    const body = {
      detail: [
        {
          loc: ['body', 'installment_count'],
          msg: 'ensure this value is greater than or equal to 2',
          type: 'value_error',
        },
      ],
    }
    const msg = extractApiErrorMessage(body)
    assert.ok(msg.includes('installment_count'))
    assert.ok(msg.includes('greater than or equal to 2'))
  })

  test('detail with only a message (no errors list)', () => {
    assert.equal(
      extractApiErrorMessage({ detail: { message: 'Just the message.' } }),
      'Just the message.',
    )
  })

  test('detail with only errors (no top-level message)', () => {
    const body = {
      detail: { errors: ['One thing broke.', 'Another thing broke.'] },
    }
    const msg = extractApiErrorMessage(body)
    assert.equal(msg, 'One thing broke. Another thing broke.')
  })
})


describe('extractApiErrorMessage — string inputs', () => {
  test('bare string returned as-is', () => {
    assert.equal(extractApiErrorMessage('boom'), 'boom')
  })

  test('JSON-encoded FastAPI body — parsed and extracted', () => {
    const body = JSON.stringify({
      detail: 'Payment option not found.',
    })
    assert.equal(extractApiErrorMessage(body), 'Payment option not found.')
  })

  test('JSON-encoded FIP1 detail — parsed and extracted', () => {
    const body = JSON.stringify({
      detail: {
        message: 'Invalid.',
        errors: ['Bad field.'],
      },
    })
    const msg = extractApiErrorMessage(body)
    assert.ok(msg.includes('Invalid.'))
    assert.ok(msg.includes('Bad field.'))
  })
})


describe('extractApiErrorMessage — fallbacks', () => {
  test('null / undefined → fallback', () => {
    assert.equal(
      extractApiErrorMessage(null, { fallback: 'Nothing to see.' }),
      'Nothing to see.',
    )
    assert.equal(
      extractApiErrorMessage(undefined, { fallback: 'Nothing to see.' }),
      'Nothing to see.',
    )
  })

  test('unknown object shape → fallback', () => {
    assert.equal(
      extractApiErrorMessage(
        { some: 'weird', shape: 42 },
        { fallback: 'Fell back.' },
      ),
      'Fell back.',
    )
  })

  test('default fallback when none provided', () => {
    const msg = extractApiErrorMessage({ some: 'weird' })
    assert.ok(msg.length > 0)
    assert.notEqual(msg, '[object Object]')
  })
})


describe('extractApiErrorMessage — Error instances', () => {
  test('Error with a plain message', () => {
    assert.equal(
      extractApiErrorMessage(new Error('save failed')),
      'save failed',
    )
  })

  test('Error whose message is JSON-encoded FIP1 detail', () => {
    const detail = JSON.stringify({
      message: 'Invalid.',
      errors: ['x'],
    })
    const msg = extractApiErrorMessage(new Error(detail))
    assert.ok(msg.includes('Invalid.'))
    assert.ok(msg.includes('x'))
  })
})
