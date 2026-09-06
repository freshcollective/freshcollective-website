/**
 * Regression tests for the collective-switch Route Handler.
 *
 * Two-part coverage:
 *
 *   * This file (structural) — assert the anti-pattern
 *     ``new URL(*, request.url)`` remains absent; assert the handler
 *     builds redirect Location via ``buildAbsoluteRedirectLocation``
 *     rather than any ad-hoc string; assert both side-effects
 *     (cookie set + layout revalidate) are preserved.
 *
 *   * ``src/lib/absoluteRedirectLocation.test.ts`` — exhaustive
 *     behavioural tests on the helper itself: production headers,
 *     local dev headers, missing headers, and the negative
 *     invariant that the result never contains ``localhost:10000``.
 *
 * Structural tests avoid mocking ``next/headers`` /
 * ``next/cache`` / ``@/lib/serverApi`` — those code paths are
 * already covered by their own unit tests and by end-to-end
 * verification. Same approach as ``src/lib/bffAuth.test.ts``.
 *
 * Run with:
 *
 *   node --experimental-strip-types --test \
 *     src/app/creator-studio/collective/switch/[slug]/route.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'


const _here = dirname(fileURLToPath(import.meta.url))
const ROUTE_PATH = join(_here, 'route.ts')
const SOURCE = readFileSync(ROUTE_PATH, 'utf-8')

// Strip the module's JSDoc / line comments so any pattern named in
// the rationale doesn't itself trip an assertion.
const CODE = SOURCE.replace(/\/\*[^]*?\*\//g, '')
  .split('\n')
  .map((line) => line.replace(/\/\/.*$/, ''))
  .join('\n')


describe('collective-switch route — production-safe redirect construction', () => {
  test('does NOT construct redirect URL from request.url (Route Handler anti-pattern on Render)', () => {
    // ``request.url`` in a Route Handler on Render is
    // ``http://localhost:$PORT/…``. Building a redirect target from
    // it would put localhost in the Location header — the exact bug
    // this test defends against.
    const antipattern = /new\s+URL\s*\([^)]*request\.url/
    assert.equal(
      antipattern.test(CODE),
      false,
      'route.ts must not build redirect URLs from request.url — ' +
        "Route Handler request.url on Render is 'http://localhost:$PORT'",
    )
  })

  test('does NOT emit any hardcoded localhost host in a Location header', () => {
    // Belt-and-braces: even a stray literal ``localhost:10000`` or
    // ``localhost:3000`` in the source would defeat the helper.
    assert.equal(
      /localhost:\d+/.test(CODE),
      false,
      'route.ts source must not reference any localhost:PORT literal',
    )
  })

  test('builds Location via buildAbsoluteRedirectLocation (helper carries the trust rules)', () => {
    // Both Location values must flow through the helper so that
    // any future refactor of the trust rules (Host header,
    // x-forwarded-proto, missing-header fallback) lands in exactly
    // one file. See src/lib/absoluteRedirectLocation.ts.
    const helperImport = /from\s+['"]@\/lib\/absoluteRedirectLocation['"]/
    assert.match(
      CODE,
      helperImport,
      'expected import { buildAbsoluteRedirectLocation } from @/lib/absoluteRedirectLocation',
    )
    const callCount = (
      CODE.match(/buildAbsoluteRedirectLocation\s*\(/g) || []
    ).length
    assert.equal(
      callCount,
      2,
      'expected exactly two calls to buildAbsoluteRedirectLocation ' +
        '(one per branch — success and unauthorized)',
    )
  })

  test('every Location header value is a call to the helper — no bare strings, no ad-hoc URLs', () => {
    // Match every ``Location: <expression>`` in the code and assert
    // the expression is a helper call. Catches accidents like a
    // future edit reintroducing a bare ``Location: '/x'`` or an
    // absolute URL literal.
    const locations = [
      ...CODE.matchAll(/Location:\s*([^,}\n]+)/g),
    ].map((m) => m[1]!.trim())
    assert.ok(locations.length >= 2, 'expected at least two Location fields')
    for (const value of locations) {
      assert.match(
        value,
        /^buildAbsoluteRedirectLocation\(/,
        `Location value "${value}" must be a call to buildAbsoluteRedirectLocation`,
      )
    }
  })

  test('preserves the two behaviours callers depend on: cookie set + layout revalidate', () => {
    assert.match(
      CODE,
      /cookieStore\.set\(ACTIVE_SPACE_COOKIE,\s*slug,/,
      'active-collective cookie set on success path',
    )
    assert.match(
      CODE,
      /revalidatePath\(['"]\/creator-studio['"],\s*['"]layout['"]\)/,
      'layout cache revalidated so the sidebar re-renders with the new active collective',
    )
  })

  test('both target paths are present (success + unauthorized)', () => {
    // Guards against a refactor that accidentally drops one of the
    // two redirect targets.
    assert.match(
      CODE,
      /['"]\/creator-studio\/home['"]/,
      'success path must redirect to /creator-studio/home',
    )
    // The unauthorized branch redirects to /creator-studio (Creator
    // Studio index). Match on the exact path with word boundary so
    // it isn't confused with /creator-studio/home.
    assert.match(
      CODE,
      /['"]\/creator-studio['"]/,
      'unauthorized path must redirect to /creator-studio',
    )
  })
})
