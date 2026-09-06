/**
 * Unit tests for ``buildAbsoluteRedirectLocation``.
 *
 * Locks in the invariants that keep production redirects away from
 * ``http://localhost:$PORT`` — see the module docstring in
 * ``absoluteRedirectLocation.ts`` for the full incident history.
 *
 * Run with:
 *
 *   node --experimental-strip-types --test \
 *     src/lib/absoluteRedirectLocation.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// @ts-expect-error - Node-native import path
import { buildAbsoluteRedirectLocation } from './absoluteRedirectLocation.ts'


function _req(headers: Record<string, string>): Request {
  return new Request('http://localhost:10000/anything', {
    headers: new Headers(headers),
  })
}


describe('buildAbsoluteRedirectLocation — production (Render + Cloudflare)', () => {
  test('Host + x-forwarded-proto produce a full https URL on the browser-facing origin', () => {
    const r = _req({
      host: 'fc-web-q950.onrender.com',
      'x-forwarded-proto': 'https',
    })
    assert.equal(
      buildAbsoluteRedirectLocation(r, '/creator-studio/home'),
      'https://fc-web-q950.onrender.com/creator-studio/home',
    )
  })

  test('missing x-forwarded-proto defaults to https (production expectation)', () => {
    const r = _req({ host: 'fc-web-q950.onrender.com' })
    assert.equal(
      buildAbsoluteRedirectLocation(r, '/creator-studio/home'),
      'https://fc-web-q950.onrender.com/creator-studio/home',
    )
  })

  test('preserves query strings and hash fragments in the path', () => {
    const r = _req({ host: 'fc-web-q950.onrender.com' })
    assert.equal(
      buildAbsoluteRedirectLocation(r, '/creator-studio?next=/foo#bar'),
      'https://fc-web-q950.onrender.com/creator-studio?next=/foo#bar',
    )
  })
})


describe('buildAbsoluteRedirectLocation — local development', () => {
  test('Host = localhost:3000 produces the correct localhost URL, not localhost:10000', () => {
    // The Host header is set by the browser to its own idea of the
    // origin. During local dev the browser hits ``localhost:3000``
    // and the Host header reflects that — so the absolute URL is
    // correct for local. Never picks up Render's internal
    // ``localhost:$PORT``.
    const r = _req({ host: 'localhost:3000', 'x-forwarded-proto': 'http' })
    assert.equal(
      buildAbsoluteRedirectLocation(r, '/creator-studio/home'),
      'http://localhost:3000/creator-studio/home',
    )
  })

  test('local dev without x-forwarded-proto defaults to https (harmless — dev browser will follow)', () => {
    // Not ideal but not broken — a dev running fc-web plain HTTP
    // without a reverse proxy in front would need to set
    // x-forwarded-proto: http. Documented as the trade-off for
    // safe production defaults.
    const r = _req({ host: 'localhost:3000' })
    assert.equal(
      buildAbsoluteRedirectLocation(r, '/creator-studio/home'),
      'https://localhost:3000/creator-studio/home',
    )
  })
})


describe('buildAbsoluteRedirectLocation — defensive fallback', () => {
  test('missing Host header falls back to a relative path', () => {
    // Host is required by HTTP/1.1 and is always set in practice.
    // If somehow missing, return the raw path so the browser
    // resolves against its own current URL — never localhost.
    const r = _req({})
    assert.equal(
      buildAbsoluteRedirectLocation(r, '/creator-studio/home'),
      '/creator-studio/home',
    )
  })

  test('never returns a URL containing "localhost:10000" (the anti-invariant)', () => {
    // Deliberate cross-check: whatever headers we throw at it, the
    // result must not include Render's internal listen port.
    const cases: Array<Record<string, string>> = [
      { host: 'fc-web-q950.onrender.com' },
      { host: 'fc-web-q950.onrender.com', 'x-forwarded-proto': 'https' },
      { host: 'localhost:3000' },
      { host: 'app.freshcollective.com', 'x-forwarded-proto': 'https' },
      {},
    ]
    for (const headers of cases) {
      const r = _req(headers)
      const location = buildAbsoluteRedirectLocation(r, '/creator-studio/home')
      assert.ok(
        !location.includes('localhost:10000'),
        `expected no localhost:10000 in Location; got ${location} with headers ${JSON.stringify(headers)}`,
      )
    }
  })
})
