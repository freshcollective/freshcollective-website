/**
 * The Stripe Connect request sequences.
 *
 * What is worth testing here is ordering and restraint: which calls are
 * made, in which order, and which are *not* made. A panel that creates a
 * second connected account, or reuses an expired link, looks entirely
 * correct on screen.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import
import {
  ACCOUNT_PATH,
  LINK_PATH,
  REFRESH_PATH,
  STATUS_PATH,
  continueConnect,
  loadStatus,
  mintOnboardingUrl,
  refreshStatus,
  sequenceFor,
  startConnect,
} from './stripeConnectActions.ts'

/** Records the call order and hands back canned responses. */
function recorder(
  responses: Record<string, unknown> = {},
  failures: Record<string, string> = {},
) {
  const calls: string[] = []
  let linkCounter = 0
  const answer = (path: string) => {
    calls.push(path)
    if (failures[path]) return Promise.reject(new Error(failures[path]))
    if (path === LINK_PATH && !(LINK_PATH in responses)) {
      linkCounter += 1
      return Promise.resolve({
        url: `https://connect.stripe.com/setup/e/acct_1/link${linkCounter}`,
        expires_in_seconds: 300,
      })
    }
    return Promise.resolve(responses[path] ?? {})
  }
  return {
    calls,
    transport: {
      get: (path: string) => answer(path),
      post: (path: string) => answer(path),
    },
  }
}

describe('first-time connect', () => {
  test('creates the account, then mints a link, in that order', async () => {
    const r = recorder()
    const url = await startConnect(r.transport)
    assert.deepEqual(r.calls, [ACCOUNT_PATH, LINK_PATH])
    assert.match(url, /^https:\/\/connect\.stripe\.com\//)
  })

  test('a failure creating the account never reaches the link call', async () => {
    const r = recorder({}, { [ACCOUNT_PATH]: 'Stripe could not be reached' })
    await assert.rejects(() => startConnect(r.transport), /could not be reached/)
    assert.deepEqual(r.calls, [ACCOUNT_PATH])
  })
})

describe('continuing an existing setup', () => {
  test('skips account creation and only mints a link', async () => {
    const r = recorder()
    await continueConnect(r.transport)
    assert.deepEqual(r.calls, [LINK_PATH])
    assert.ok(!r.calls.includes(ACCOUNT_PATH))
  })

  test('every call yields a different URL — none is reused', async () => {
    const r = recorder()
    const first = await continueConnect(r.transport)
    const second = await continueConnect(r.transport)
    assert.notEqual(first, second)
    assert.deepEqual(r.calls, [LINK_PATH, LINK_PATH])
  })

  test('a link response with no URL is an error, not a silent no-op', async () => {
    const r = recorder({ [LINK_PATH]: { expires_in_seconds: 300 } })
    await assert.rejects(() => mintOnboardingUrl(r.transport), /did not return a setup link/)
  })
})

describe('which sequence a state needs', () => {
  test('not_started starts from scratch', () => {
    assert.equal(sequenceFor('not_started'), 'start')
  })

  test('the three resumable states continue', () => {
    for (const state of ['onboarding', 'action_required', 'transfers_only']) {
      assert.equal(sequenceFor(state), 'continue', state)
    }
  })

  test('terminal and complete states offer no sequence', () => {
    for (const state of ['ready', 'verifying', 'restricted', 'unsupported', 'closed']) {
      assert.equal(sequenceFor(state), 'none', state)
    }
  })
})

describe('status reads', () => {
  test('loading status is a GET against the status endpoint', async () => {
    const r = recorder({ [STATUS_PATH]: { state: 'ready' } })
    const status = await loadStatus(r.transport)
    assert.deepEqual(r.calls, [STATUS_PATH])
    assert.equal(status.state, 'ready')
  })

  test('refreshing posts to the refresh endpoint and returns the new state', async () => {
    const r = recorder({ [REFRESH_PATH]: { state: 'ready', connect_routing_enabled: false } })
    const status = await refreshStatus(r.transport)
    assert.deepEqual(r.calls, [REFRESH_PATH])
    assert.equal(status.state, 'ready')
    assert.equal(status.connect_routing_enabled, false)
  })

  test('a failing refresh rejects so the caller can keep the creator informed', async () => {
    const r = recorder({}, { [REFRESH_PATH]: 'Stripe could not be reached just now.' })
    await assert.rejects(() => refreshStatus(r.transport), /could not be reached/)
  })
})

describe('double submission', () => {
  /**
   * Mirrors the panel's guard: one in-flight flag across every action, so a
   * second click during a request is dropped rather than queued. Creating a
   * connected account twice is not something that can be tidied up
   * afterwards.
   */
  function guarded() {
    let inFlight = false
    const ran: number[] = []
    let n = 0
    return async function run(work: () => Promise<void>) {
      if (inFlight) return
      inFlight = true
      try {
        n += 1
        ran.push(n)
        await work()
      } finally {
        inFlight = false
      }
    }
  }

  test('a second click during an in-flight request is ignored', async () => {
    const r = recorder()
    const run = guarded()
    let release: (() => void) | null = null
    const gate = new Promise<void>((resolve) => { release = resolve })

    const first = run(async () => {
      await gate
      await startConnect(r.transport)
    })
    // Second click while the first is still open.
    await run(async () => { await startConnect(r.transport) })
    release!()
    await first

    assert.deepEqual(r.calls, [ACCOUNT_PATH, LINK_PATH])
  })

  test('after a request settles, the next click works', async () => {
    const r = recorder()
    const run = guarded()
    await run(async () => { await continueConnect(r.transport) })
    await run(async () => { await continueConnect(r.transport) })
    assert.deepEqual(r.calls, [LINK_PATH, LINK_PATH])
  })

  test('a failed request releases the guard', async () => {
    const r = recorder({}, { [LINK_PATH]: 'boom' })
    const run = guarded()
    await run(async () => {
      try { await continueConnect(r.transport) } catch { /* surfaced in the UI */ }
    })
    await run(async () => {
      try { await continueConnect(r.transport) } catch { /* surfaced in the UI */ }
    })
    assert.equal(r.calls.length, 2)
  })
})

describe('return and refresh pages', () => {
  test('the return page refreshes rather than trusting the redirect', async () => {
    // Landing back from Stripe proves nothing — Stripe returns the browser
    // on abandonment too.
    const r = recorder({ [REFRESH_PATH]: { state: 'transfers_only' } })
    const status = await refreshStatus(r.transport)
    assert.deepEqual(r.calls, [REFRESH_PATH])
    assert.ok(!r.calls.includes(STATUS_PATH))
    assert.equal(status.state, 'transfers_only')
  })

  test('the refresh page always mints a new link', async () => {
    const r = recorder()
    const first = await mintOnboardingUrl(r.transport)
    const second = await mintOnboardingUrl(r.transport)
    assert.deepEqual(r.calls, [LINK_PATH, LINK_PATH])
    assert.notEqual(first, second)
  })
})
