/**
 * Regression tests for the collective-switch Route Handler.
 *
 * Backstory: a production Route Handler that built its redirect target
 * with ``new URL(path, request.url)`` sent Lindsey's browser to
 * ``http://localhost:10000/creator-studio/home`` after onboarding
 * completion and every time she clicked a Collective card. The
 * ``request.url`` inside a Route Handler on Render is the container's
 * internal listen address (Render forwards to Node on
 * ``http://localhost:$PORT``), so the resulting Location header
 * pointed the browser at localhost.
 *
 * The fix uses a RELATIVE ``Location`` header — per RFC 7231 §7.1.2,
 * browsers resolve relative Location against the effective request
 * URI from the browser's perspective (the public origin), so no
 * server-derived base URL is involved.
 *
 * These tests enforce the invariant structurally, in the same way
 * ``src/lib/bffAuth.test.ts`` enforces the SEC-002 response allowlist:
 * read the source, assert the anti-pattern is absent and the
 * corrected pattern is present. Structural checks catch a future
 * refactor that reintroduces the bug without needing to mock the
 * Next.js ``cookies()`` / ``revalidatePath`` / server-API surface.
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


describe('collective-switch route — redirect target is browser-resolvable', () => {
  test('does NOT construct redirect URL from request.url (Route Handler anti-pattern on Render)', () => {
    // The exact anti-pattern this test defends against —
    // ``new URL(path, request.url)`` inside a Route Handler — yields
    // ``http://localhost:$PORT/...`` on Render. Strip the module's
    // JSDoc/docstring first so the pattern named in the fix
    // rationale doesn't itself trip the assertion.
    const stripped = SOURCE.replace(/\/\*[^]*?\*\//g, '')
      .split('\n')
      .map((line) => line.replace(/\/\/.*$/, ''))
      .join('\n')
    const antipattern = /new\s+URL\s*\([^)]*request\.url/
    assert.equal(
      antipattern.test(stripped),
      false,
      'route.ts must not build redirect URLs from request.url — ' +
        "Route Handler request.url on Render is 'http://localhost:$PORT'",
    )
  })

  test('the request parameter is unused (underscore-prefixed) so no future edit is tempted to read it', () => {
    // Belt-and-braces: if request is not received into scope, no
    // future edit can accidentally reintroduce ``request.url``
    // without also editing the signature. The prefix documents the
    // decision.
    assert.match(
      SOURCE,
      /export\s+async\s+function\s+GET\s*\(\s*_request\s*:\s*Request/,
      "expected 'export async function GET(_request: Request, ...)' — " +
        "the underscore prefix signals request is deliberately unused",
    )
  })

  test('success path returns 303 with relative Location "/creator-studio/home"', () => {
    // The "allowed slug" branch must land the creator on their new
    // Collective home. Location is relative — browsers resolve it
    // against the public origin.
    assert.match(
      SOURCE,
      /status:\s*303[^]{0,120}Location:\s*['"]\/creator-studio\/home['"]/,
      "expected a 303 response with Location: '/creator-studio/home'",
    )
  })

  test('unauthorized path returns 303 with relative Location "/creator-studio"', () => {
    // The "not-in-allowed-spaces" branch must send the caller back
    // to the Creator Studio index — not to localhost.
    assert.match(
      SOURCE,
      /status:\s*303[^]{0,120}Location:\s*['"]\/creator-studio['"]/,
      "expected a 303 response with Location: '/creator-studio'",
    )
  })

  test('no absolute URLs (http:// or https://) appear in Location values', () => {
    // Scan every ``Location: '...'`` and ``Location: "..."`` and
    // assert the value starts with a single slash. Catches any
    // future revision that hard-codes an absolute production URL
    // (which would break preview environments) or reintroduces a
    // scheme via string concatenation.
    const locations = [
      ...SOURCE.matchAll(/Location:\s*['"]([^'"]+)['"]/g),
    ].map((m) => m[1]!)
    assert.ok(locations.length >= 2, 'expected at least two Location values')
    for (const loc of locations) {
      assert.equal(
        loc.startsWith('/') && !loc.startsWith('//'),
        true,
        `Location "${loc}" must be a same-origin relative path ` +
          '(single leading slash, no scheme, no protocol-relative form)',
      )
    }
  })

  test('preserves the two behaviours callers depend on: cookie set + layout revalidate', () => {
    // The fix must not have accidentally dropped either of these
    // side effects — they are why the switch route exists at all.
    // Cookie set: sidebar reads ACTIVE_SPACE_COOKIE to identify the
    // active collective. revalidatePath: dynamic-route cache would
    // otherwise serve the previous layout for one navigation cycle.
    assert.match(
      SOURCE,
      /cookieStore\.set\(ACTIVE_SPACE_COOKIE,\s*slug,/,
      'active-collective cookie set on success path',
    )
    assert.match(
      SOURCE,
      /revalidatePath\(['"]\/creator-studio['"],\s*['"]layout['"]\)/,
      'layout cache revalidated so the sidebar re-renders with the new active collective',
    )
  })
})
