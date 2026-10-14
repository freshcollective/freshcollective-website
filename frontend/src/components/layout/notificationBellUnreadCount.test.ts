/**
 * The bell showed no badge until you opened it.
 *
 * `initialCount` is 0 at every call site, and `setInterval` has no
 * leading call, so a freshly loaded page displayed an unread count of
 * zero for a full minute regardless of how many notifications were
 * waiting. Opening the dropdown was the only reliable way to correct
 * it, because `fetchNotifications` sets the count as a side effect.
 *
 * The fix is a mount-and-navigation effect. These tests pin it, plus
 * the behaviour around it that must not have moved: the 60-second
 * poll, the focus listener, the open-the-dropdown fetch, and both
 * read paths.
 *
 * The project has no DOM renderer (node:test only, no testing-library
 * or jsdom), so this reads the source. Comments are stripped with the
 * same quote-aware walker used by uploadNetworkErrors.test.ts — the
 * naive regex version treats `accept="image/*"` as a comment opener
 * and deletes the code under test.
 */

import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

function codeOnly(src: string): string {
  let out = ''
  let i = 0
  let quote: string | null = null
  while (i < src.length) {
    const c = src[i]
    const next = src[i + 1]
    if (quote) {
      out += c
      if (c === '\\') { out += next ?? ''; i += 2; continue }
      if (c === quote) quote = null
      i += 1
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; out += c; i += 1; continue }
    if (c === '/' && next === '*') {
      const end = src.indexOf('*/', i + 2)
      i = end === -1 ? src.length : end + 2
      continue
    }
    if (c === '/' && next === '/') {
      const end = src.indexOf('\n', i)
      i = end === -1 ? src.length : end
      continue
    }
    out += c
    i += 1
  }
  return out
}

const BELL = codeOnly(
  readFileSync('src/components/layout/NotificationBell.tsx', 'utf8'),
)

/** Every `useEffect(() => { ... }, [deps])` as a {body, deps} pair. */
function effects(src: string): { body: string; deps: string }[] {
  const out: { body: string; deps: string }[] = []
  let from = 0
  for (;;) {
    const start = src.indexOf('useEffect(', from)
    if (start === -1) return out
    let i = src.indexOf('{', start)
    if (i === -1) return out
    let depth = 0
    const bodyStart = i
    for (; i < src.length; i += 1) {
      if (src[i] === '{') depth += 1
      else if (src[i] === '}') {
        depth -= 1
        if (depth === 0) break
      }
    }
    const body = src.slice(bodyStart, i + 1)
    const tail = src.slice(i + 1, src.indexOf(')', i + 1) + 1)
    out.push({ body, deps: tail })
    from = i + 1
  }
}

const EFFECTS = effects(BELL)

// ---------------------------------------------------------------------------
// 1 · The count is fetched without being asked for
// ---------------------------------------------------------------------------

describe('the badge is correct before the user touches anything', () => {
  test('a dedicated effect reads the unread count', () => {
    // Not merely "some effect mentions reading the count": the focus
    // handler lives inside the polling effect and would satisfy that,
    // which is how the first version of this test passed against the
    // bug it was written to catch. What is required is an effect that
    // reads on run — one that sets up no timer and no listener.
    const immediate = EFFECTS.filter(
      (e) =>
        /readUnreadCount\(\)/.test(e.body) &&
        !/setInterval\(/.test(e.body) &&
        !/addEventListener\(/.test(e.body),
    )
    assert.ok(
      immediate.length > 0,
      'no effect reads the count on run — the badge waits for the ' +
        '60s tick, a window focus, or the user opening the dropdown',
    )
  })

  test('its result is applied to the badge', () => {
    // Reading without setting would satisfy the test above and fix
    // nothing.
    const [effect] = EFFECTS.filter(
      (e) =>
        /readUnreadCount\(\)/.test(e.body) &&
        !/setInterval\(/.test(e.body) &&
        !/addEventListener\(/.test(e.body),
    )
    assert.ok(effect, 'no mount/navigation effect found')
    assert.match(effect.body, /setUnreadCount\(count\)/)
  })

  test('a late answer cannot overwrite a newer one', () => {
    // Two navigations in quick succession leave two requests in
    // flight. Without a guard the slower one lands last.
    const [effect] = EFFECTS.filter(
      (e) =>
        /readUnreadCount\(\)/.test(e.body) &&
        !/setInterval\(/.test(e.body) &&
        !/addEventListener\(/.test(e.body),
    )
    assert.ok(effect, 'no mount/navigation effect found')
    assert.match(effect.body, /cancelled = true/, 'no cleanup sets the flag')
    assert.match(
      effect.body,
      /if \(!cancelled/,
      'the flag is set but never checked before setState',
    )
  })

  test('that effect also re-runs on navigation', () => {
    const onNav = EFFECTS.filter(
      (e) => /readUnreadCount\(\)/.test(e.body) && /pathname/.test(e.deps),
    )
    assert.ok(
      onNav.length > 0,
      'no fetch effect depends on pathname, so moving between sections ' +
        'leaves a remounted bell showing zero',
    )
  })

  test('pathname comes from the router, not something hand-rolled', () => {
    assert.match(BELL, /import \{[^}]*usePathname[^}]*\} from 'next\/navigation'/)
    assert.match(BELL, /const pathname = usePathname\(\)/)
  })
})

// ---------------------------------------------------------------------------
// 2 · Nothing around it moved
// ---------------------------------------------------------------------------

describe('the existing behaviour is unchanged', () => {
  test('the 60-second poll is still there', () => {
    assert.match(BELL, /setInterval\(fetchUnreadCount, 60000\)/)
  })

  test('the poll is cleaned up', () => {
    assert.match(BELL, /clearInterval\(interval\)/)
  })

  test('the focus listener is still there and is removed', () => {
    assert.match(BELL, /addEventListener\('focus', onFocus\)/)
    assert.match(BELL, /removeEventListener\('focus', onFocus\)/)
  })

  test('opening the dropdown still fetches notifications', () => {
    assert.match(BELL, /if \(!open\) \{\s*void fetchNotifications\(\)/)
  })

  test('mark-all-read still posts and zeroes the count', () => {
    assert.match(BELL, /\/api\/notifications\/read-all/)
    assert.match(BELL, /setUnreadCount\(0\)/)
  })

  test('clicking a row still marks it read and decrements', () => {
    assert.match(BELL, /markNotificationRead\(notif\.id\)/)
    assert.match(BELL, /setUnreadCount\(\(prev\) => Math\.max\(0, prev - 1\)\)/)
  })
})

// ---------------------------------------------------------------------------
// 3 · No extra polling was introduced
// ---------------------------------------------------------------------------

describe('no duplicate or extra polling', () => {
  test('there is exactly one interval', () => {
    const intervals = BELL.match(/setInterval\(/g) ?? []
    assert.equal(intervals.length, 1, `expected 1 setInterval, found ${intervals.length}`)
  })

  test('the poll is not restarted by navigation', () => {
    // The timer must live in its own effect. Sharing one with the
    // pathname-keyed fetch would tear down and recreate the interval
    // on every navigation, so a user moving around often would never
    // reach a 60-second tick.
    const timerEffects = EFFECTS.filter((e) => /setInterval\(/.test(e.body))
    assert.equal(timerEffects.length, 1)
    assert.ok(
      !/pathname/.test(timerEffects[0].deps),
      'the interval effect depends on pathname, so navigation restarts the timer',
    )
  })

  test('the unread-count endpoint is named in exactly one place', () => {
    // Both the poll and the mount/navigation read go through
    // readUnreadCount, so a second reference would mean a second,
    // divergent way of asking.
    const calls = BELL.match(/\/api\/notifications\/unread-count/g) ?? []
    assert.equal(calls.length, 1, 'the endpoint is referenced more than once')
  })

  test('the poll still goes through the shared reader', () => {
    assert.match(BELL, /const fetchUnreadCount = useCallback\(async \(\) => \{\s*const count = await readUnreadCount\(\)/)
  })
})
