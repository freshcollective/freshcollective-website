/**
 * The beacon's contract with the rest of the app.
 *
 * Two properties here are load-bearing and neither is visible in
 * behaviour until it is too late:
 *
 *  1. ``spa: false``. Cloudflare's SPA mode works by patching
 *     ``history.pushState``. Once installed, that patch reports every
 *     route the visitor opens — a signed-in member who arrived via a
 *     public page would have their dashboard and their private
 *     conversations reported, and unmounting the element would not
 *     undo it. Turning SPA mode on would quietly defeat the entire
 *     allow-list.
 *
 *  2. A classic script, not ``type="module"``. A module script is
 *     evaluated once per URL per document, so re-inserting it after a
 *     client-side navigation would do nothing and only the first page
 *     of each visit would be counted.
 *
 * Source-contract tests: the project has no DOM renderer (node:test,
 * no jsdom), so the component is pinned by reading its source.
 * Comments are stripped with the quote-aware walker used elsewhere —
 * the naive regex treats `accept="image/*"` as a comment opener.
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

const read = (p: string) => codeOnly(readFileSync(p, 'utf8'))

const BEACON = read('src/components/analytics/CloudflareAnalytics.tsx')
const LAYOUT = read('src/app/layout.tsx')
const HEADERS = read('src/lib/securityHeaders.ts')

// ---------------------------------------------------------------------------
// 1 · SPA mode is off, and must stay off
// ---------------------------------------------------------------------------

describe('the beacon cannot follow a visitor', () => {
  test('SPA mode is explicitly disabled', () => {
    // Required, not defensive: read from the beacon source
    // (js 2026.10.1), ``spa == null`` resolves to
    // ``HistoryAndNavigationAPI``, so the dashboard's own snippet —
    // which carries no ``spa`` key — patches the History API. Only
    // ``spa: false`` resolves to ``None``, and the whole
    // instrumentation block (soft-navigation observer, Navigation API
    // listener, pushState patch, popstate listener) sits behind that
    // single check.
    assert.match(BEACON, /spa: false/)
    assert.ok(
      !/spa: true/.test(BEACON),
      'SPA mode patches history.pushState and would report every route '
        + 'the visitor opens, defeating the allow-list entirely — and '
        + 'the popstate listener it adds cannot be intercepted at all',
    )
  })

  test('multi-load is enabled, or nothing after the first page reports', () => {
    // The other half, and the one that looks removable. ``load``
    // defaults to ``"single"``; on a second execution the beacon hits
    // ``"single" === window.__cfBeacon.load`` and returns *before* the
    // token gate and before any code path that transmits — the page
    // view it just recorded sits in a closure-local buffer that is
    // then abandoned. So without this key, client-side navigation is
    // not under-counted, it is not counted at all, and nothing fails
    // loudly to say so.
    //
    // It survives across executions because the beacon's config merge
    // is ``Object.assign({}, parsed, window.__cfBeacon)`` — the value
    // the first execution stored wins over each later parse.
    assert.match(BEACON, /load: 'multi'/)
  })

  test('both settings travel in the data attribute, where they are read', () => {
    // ``load`` is only honoured from ``data-cf-beacon``: the beacon's
    // src-query parser reads ``token`` and ``spa`` and nothing else.
    assert.match(
      BEACON,
      /'data-cf-beacon',\s*JSON\.stringify\(\{ token: BEACON_TOKEN, spa: false, load: 'multi' \}\)/,
    )
  })

  test('the accumulation it causes is documented, not discovered later', () => {
    // A reader who finds ten visibilitychange listeners in a long
    // session should find the reason in this file rather than in a
    // bug report.
    const raw = readFileSync('src/components/analytics/CloudflareAnalytics.tsx', 'utf8')
    assert.match(raw, /Known limitation/)
    assert.match(raw, /Core Web Vitals/)
  })

  test('the beacon is a classic script, so it can report per page', () => {
    assert.ok(
      !/type = ?["']module["']|type=["']module["']/.test(BEACON),
      'a module script evaluates once per document — only the first '
        + 'page of each visit would be counted',
    )
    assert.match(BEACON, /createElement\('script'\)/)
  })
})

// ---------------------------------------------------------------------------
// 2 · Nothing is reported that the allow-list refuses
// ---------------------------------------------------------------------------

describe('every report is gated', () => {
  test('the allow-list decides, and it is the shared one', () => {
    assert.match(BEACON, /import \{ isTrackablePath \} from '@\/lib\/analytics'/)
    assert.match(BEACON, /if \(!pathname \|\| !isTrackablePath\(pathname\)\) return/)
  })

  test('the gate comes before anything is created or sent', () => {
    const gate = BEACON.indexOf('isTrackablePath(pathname)')
    const create = BEACON.indexOf("createElement('script')")
    assert.ok(gate !== -1 && create !== -1 && gate < create)
  })

  test('the same page is never reported twice', () => {
    // A re-render, a search-parameter change, or React's development
    // double-effect must not produce a second page view.
    assert.match(BEACON, /reported = useRef<string \| null>\(null\)/)
    assert.match(BEACON, /if \(reported\.current === pathname\) return/)
    assert.match(BEACON, /reported\.current = pathname/)
  })

  test('only the pathname is read — never a session or an identifier', () => {
    assert.match(BEACON, /usePathname\(\)/)
    // Named precisely rather than by keyword. A blunt /user/i here
    // matches ``useRef`` and fails on the import line, which is the
    // kind of assertion that gets deleted rather than fixed.
    for (const banned of [
      /useSearchParams/, /document\.cookie/, /localStorage/,
      /sessionStorage/, /getMe\b/, /currentUser/, /userId/, /user_id/,
      /email/i, /\btoken\b(?!: BEACON_TOKEN)/,
    ]) {
      assert.ok(
        !banned.test(BEACON),
        `${banned} — the component must know nothing about who is looking`,
      )
    }
  })

  test('it renders nothing', () => {
    assert.match(BEACON, /return null/)
  })
})

// ---------------------------------------------------------------------------
// 3 · Wiring
// ---------------------------------------------------------------------------

describe('wiring', () => {
  test('it is mounted once, in the root layout', () => {
    assert.match(LAYOUT, /import CloudflareAnalytics/)
    assert.equal((LAYOUT.match(/<CloudflareAnalytics \/>/g) ?? []).length, 1)
  })

  test('the layout is not made dynamic to support it', () => {
    // Reading cookies() or headers() here would opt every route in the
    // app out of static rendering — eight pages today, including
    // /about and /discover-places.
    for (const banned of [/cookies\(/, /headers\(/, /force-dynamic/]) {
      assert.ok(!banned.test(LAYOUT), `${banned} in the root layout`)
    }
  })

  test('it loads only the beacon, from Cloudflare only', () => {
    assert.match(BEACON, /https:\/\/static\.cloudflareinsights\.com\/beacon\.min\.js/)
    assert.equal((BEACON.match(/https:\/\//g) ?? []).length, 1)
  })

  test('stale beacon elements are cleaned up rather than accumulated', () => {
    assert.match(BEACON, /querySelectorAll[\s\S]{0,80}remove\(\)/)
  })
})

// ---------------------------------------------------------------------------
// 4 · The CSP permits exactly the two origins needed
// ---------------------------------------------------------------------------

describe('the policy grants no more than the beacon needs', () => {
  test('the script host is in script-src', () => {
    assert.match(HEADERS, /CF_ANALYTICS_SCRIPT_ORIGIN = 'https:\/\/static\.cloudflareinsights\.com'/)
    assert.match(HEADERS, /'script-src': \[[\s\S]{0,400}CF_ANALYTICS_SCRIPT_ORIGIN/)
  })

  test('the reporting host is in connect-src, and is a different origin', () => {
    assert.match(HEADERS, /CF_ANALYTICS_REPORT_ORIGIN = 'https:\/\/cloudflareinsights\.com'/)
    assert.match(HEADERS, /'connect-src': \[[\s\S]{0,300}CF_ANALYTICS_REPORT_ORIGIN/)
  })

  test('neither origin is a wildcard', () => {
    assert.ok(
      !/cloudflareinsights/.test(HEADERS.replace(/https:\/\/(static\.)?cloudflareinsights\.com/g, '')),
      'only the two exact origins may appear',
    )
  })
})
