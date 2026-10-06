/**
 * Reporting from an error boundary, exactly once, and only when nothing
 * else already did.
 *
 * Both of the rules here exist because of how Next reports errors, not
 * because of React. A server component's throw is reported by
 * ``onRequestError`` with the real stack and then *also* handed to the
 * client boundary as a stripped error — so capturing from the boundary
 * would file a second, worse issue for one failure. And a boundary
 * re-renders, and React invokes effects twice in StrictMode, so "once"
 * has to be a property of the error rather than of the caller's
 * dependency array.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/sentryBoundary.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import { shouldReportBoundaryError } from './sentryBoundary.ts'

describe('a server error is not filed twice', () => {
  test('an error carrying a digest is declined', () => {
    // ``digest`` is Next's mark for an error that crossed the server
    // boundary. ``onRequestError`` has it already, with the stack this
    // copy does not have.
    const error = Object.assign(new Error('An error occurred in the Server Components render'), {
      digest: '2918374651',
    })
    assert.equal(shouldReportBoundaryError(error), false)
  })

  test('an error without one is reported', () => {
    assert.equal(shouldReportBoundaryError(new Error('client-side render failed')), true)
  })

  test('a non-string digest does not count as one', () => {
    // Defensive: only Next's own marker suppresses reporting.
    const error = Object.assign(new Error('x'), { digest: 12345 })
    assert.equal(shouldReportBoundaryError(error), true)
  })
})

describe('once per error object', () => {
  test('a second attempt on the same error is declined', () => {
    const error = new Error('one failure')
    assert.equal(shouldReportBoundaryError(error), true)
    assert.equal(shouldReportBoundaryError(error), false)
    assert.equal(shouldReportBoundaryError(error), false)
  })

  test('two different errors are both reported', () => {
    assert.equal(shouldReportBoundaryError(new Error('first')), true)
    assert.equal(shouldReportBoundaryError(new Error('second')), true)
  })

  test('two errors with identical messages are still two errors', () => {
    // Keyed on identity, not on text: a component that fails twice for
    // genuinely different reasons should be visible twice.
    assert.equal(shouldReportBoundaryError(new Error('same words')), true)
    assert.equal(shouldReportBoundaryError(new Error('same words')), true)
  })
})

describe('defensive cases', () => {
  for (const value of [null, undefined, 'a string someone threw', 42]) {
    test(`a non-object is not reported: ${String(value)}`, () => {
      assert.equal(shouldReportBoundaryError(value), false)
    })
  }

  test('a thrown plain object is reported', () => {
    // Rare but real — some libraries reject with an object literal.
    assert.equal(shouldReportBoundaryError({ message: 'not an Error' }), true)
  })
})
