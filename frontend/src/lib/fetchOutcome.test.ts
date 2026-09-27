/**
 * Unit tests for the three-state read of a server request.
 *
 * The regression these exist for: the messages pages collapsed every
 * unhappy path into the happy one, so a 500 rendered as an empty inbox and
 * a dropped connection rendered as a missing thread. The backend answered
 * 500 for every member for three weeks and the UI never once said so.
 *
 * Kept as a pure module with no Next.js imports — the same reason
 * ``resolveAuthAction`` is split out of ``requireAuthenticatedUser`` — so
 * every branch runs under the built-in Node test runner:
 *
 *   node --experimental-strip-types --test src/lib/fetchOutcome.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path
import {
  GENERIC_FAILURE,
  buildOutcome,
  classifyStatus,
  failureError,
} from './fetchOutcome.ts'


describe('classifyStatus — the three states stay apart', () => {
  test('a 200 is ok', () => {
    assert.equal(classifyStatus(200), 'ok')
  })

  test('every 2xx is ok', () => {
    for (const s of [200, 201, 202, 204, 299]) {
      assert.equal(classifyStatus(s), 'ok', `status ${s}`)
    }
  })

  test('404 is missing, not a failure', () => {
    assert.equal(classifyStatus(404), 'missing')
  })

  test('403 is missing too — not yours reads as not there', () => {
    assert.equal(classifyStatus(403), 'missing')
  })

  test('500 is a failure, NOT an empty result', () => {
    // The whole bug in one assertion.
    assert.equal(classifyStatus(500), 'failure')
  })

  test('every 5xx is a failure', () => {
    for (const s of [500, 502, 503, 504]) {
      assert.equal(classifyStatus(s), 'failure', `status ${s}`)
    }
  })

  test('a request that never completed is a failure', () => {
    // No status exists, so there is nothing to mistake for data.
    assert.equal(classifyStatus(null), 'failure')
  })

  test('401 is a failure, because the auth guard runs first', () => {
    assert.equal(classifyStatus(401), 'failure')
  })

  test('an unexpected status is a failure rather than silently ok', () => {
    for (const s of [301, 302, 400, 409, 418, 429]) {
      assert.equal(classifyStatus(s), 'failure', `status ${s}`)
    }
  })
})


describe('buildOutcome — an empty list is data', () => {
  test('a 200 with an empty array is ok, and stays empty', () => {
    const outcome = buildOutcome<string[]>({ status: 200, data: [] })
    assert.equal(outcome.kind, 'ok')
    assert.deepEqual(outcome.kind === 'ok' ? outcome.data : null, [])
  })

  test('a 200 with rows is ok', () => {
    const outcome = buildOutcome<string[]>({ status: 200, data: ['a'] })
    assert.equal(outcome.kind, 'ok')
    assert.deepEqual(outcome.kind === 'ok' ? outcome.data : null, ['a'])
  })

  test('a genuinely empty inbox and a 500 are NOT the same outcome', () => {
    const empty = buildOutcome<string[]>({ status: 200, data: [] })
    const broken = buildOutcome<string[]>({ status: 500, message: 'boom' })
    assert.notEqual(empty.kind, broken.kind)
    assert.equal(empty.kind, 'ok')
    assert.equal(broken.kind, 'failure')
  })

  test('a missing thread carries no data and no message', () => {
    assert.deepEqual(buildOutcome({ status: 404 }), { kind: 'missing' })
  })

  test('a failure keeps its message and status for the log', () => {
    const outcome = buildOutcome({ status: 503, message: 'Service Unavailable' })
    assert.equal(outcome.kind, 'failure')
    if (outcome.kind !== 'failure') return
    assert.equal(outcome.message, 'Service Unavailable')
    assert.equal(outcome.status, 503)
  })

  test('a failure with nothing readable still says something', () => {
    const outcome = buildOutcome({ status: 500, message: null })
    assert.equal(outcome.kind, 'failure')
    if (outcome.kind !== 'failure') return
    assert.equal(outcome.message, GENERIC_FAILURE)
  })

  test('a whitespace-only message is treated as nothing readable', () => {
    const outcome = buildOutcome({ status: 500, message: '   ' })
    assert.equal(outcome.kind === 'failure' && outcome.message, GENERIC_FAILURE)
  })

  test('a request that never completed has a null status', () => {
    const outcome = buildOutcome({ status: null, message: 'fetch failed' })
    assert.equal(outcome.kind, 'failure')
    if (outcome.kind !== 'failure') return
    assert.equal(outcome.status, null)
    assert.equal(outcome.message, 'fetch failed')
  })

  test('a 2xx whose body would not parse is a failure, not an empty list', () => {
    // The one case where "ok" would still be a lie: the server answered,
    // but nothing usable came out of it.
    const outcome = buildOutcome<string[]>({ status: 200 })
    assert.equal(outcome.kind, 'failure')
  })

  test('a 204 with no body is a failure for a caller expecting data', () => {
    assert.equal(buildOutcome<string[]>({ status: 204 }).kind, 'failure')
  })
})


describe('failureError — what reaches app/error.tsx', () => {
  test('names the operation and the status', () => {
    const outcome = buildOutcome({ status: 500, message: 'Internal Server Error' })
    assert.equal(outcome.kind, 'failure')
    if (outcome.kind !== 'failure') return

    const err = failureError(outcome, 'Loading messages')

    assert.ok(err instanceof Error)
    assert.match(err.message, /Loading messages/)
    assert.match(err.message, /HTTP 500/)
    assert.match(err.message, /Internal Server Error/)
  })

  test('says so plainly when there was no response at all', () => {
    const outcome = buildOutcome({ status: null, message: 'fetch failed' })
    assert.equal(outcome.kind, 'failure')
    if (outcome.kind !== 'failure') return

    assert.match(failureError(outcome, 'Loading this conversation').message,
      /no response/)
  })
})


describe('the states a messages page must tell apart', () => {
  // Written as the page reads them, so the distinction the bug erased is
  // asserted as behaviour rather than as three separate unit results.
  const pageBehaviour = (outcome: ReturnType<typeof buildOutcome>) => {
    if (outcome.kind === 'missing') return 'notFound'
    if (outcome.kind === 'failure') return 'error'
    return Array.isArray(outcome.data) && outcome.data.length === 0
      ? 'empty-state'
      : 'render'
  }

  test('an empty inbox shows the empty state', () => {
    assert.equal(pageBehaviour(buildOutcome({ status: 200, data: [] })), 'empty-state')
  })

  test('a populated inbox renders', () => {
    assert.equal(pageBehaviour(buildOutcome({ status: 200, data: ['t'] })), 'render')
  })

  test('a missing thread is a not-found, not an error page', () => {
    assert.equal(pageBehaviour(buildOutcome({ status: 404 })), 'notFound')
  })

  test('a thread that is not yours is a not-found too', () => {
    assert.equal(pageBehaviour(buildOutcome({ status: 403 })), 'notFound')
  })

  test('a server failure is an error page, NOT an empty inbox', () => {
    assert.equal(pageBehaviour(buildOutcome({ status: 500 })), 'error')
  })

  test('a network failure is an error page, NOT a missing thread', () => {
    assert.equal(pageBehaviour(buildOutcome({ status: null })), 'error')
  })
})
