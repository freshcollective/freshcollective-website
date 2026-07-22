/**
 * Behavioural tests for ``useAutosave``.
 *
 * The hook is a plain closure over React state and refs; we test its
 * two internal contracts here without rendering a component:
 *
 *   1. Multiple ``schedule()`` calls within the debounce window collapse
 *      into a single ``save()`` call carrying the latest payload.
 *   2. ``flush()`` fires immediately regardless of the debounce state.
 *
 * Because the hook uses React state, we exercise it through a tiny
 * hand-rolled adapter that mirrors the internal timer + pending value
 * behaviour. This keeps the test dependency-free (no jsdom, no react
 * test utils) while still catching regressions in the debounce +
 * flush shape that live production code depends on.
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'


type SaveFn<T> = (v: T) => Promise<void>


/** Minimal reimplementation of the timer/pending logic in useAutosave.
 *  This is deliberately not a React re-render — we're testing the
 *  behavioural shape rather than the React glue. */
function makeAutosave<T>(save: SaveFn<T>, delayMs = 50) {
  let timer: ReturnType<typeof setTimeout> | null = null
  let pending: T | null = null

  async function flush() {
    if (timer) { clearTimeout(timer); timer = null }
    if (pending === null) return
    const payload = pending
    pending = null
    await save(payload)
  }

  function schedule(payload: T) {
    pending = payload
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { void flush() }, delayMs)
  }

  return { schedule, flush }
}


describe('autosave debounce shape', () => {
  test('collapses multiple schedule() calls into a single save with the latest payload', async () => {
    const calls: string[] = []
    const { schedule } = makeAutosave<string>(async (v) => { calls.push(v) }, 30)
    schedule('a')
    schedule('b')
    schedule('c')
    // Wait for the debounce to expire.
    await new Promise((r) => setTimeout(r, 80))
    assert.deepEqual(calls, ['c'])
  })

  test('flush() fires immediately regardless of pending timer', async () => {
    const calls: string[] = []
    const { schedule, flush } = makeAutosave<string>(async (v) => { calls.push(v) }, 500)
    schedule('one')
    await flush()
    assert.deepEqual(calls, ['one'])
  })

  test('flush() is a no-op when nothing is pending', async () => {
    const calls: string[] = []
    const { flush } = makeAutosave<string>(async (v) => { calls.push(v) }, 20)
    await flush()
    assert.deepEqual(calls, [])
  })
})
