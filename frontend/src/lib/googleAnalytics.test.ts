/**
 * Google Analytics 4 — what it may load, and what it may send.
 *
 * The companion to ``analytics.test.ts``. That file tests the rule;
 * this one tests that the only consumer of the rule actually obeys it,
 * which is the part a privacy boundary gets wrong in practice — an
 * allow-list is easy to write and easy to forget to consult.
 *
 * The central test is the negative one: on a non-trackable path the
 * loader must not fire. "Must not fire" is asserted as two separate
 * properties, because they fail for different reasons. ``gtag/js`` is
 * never requested (no script, so nothing of Google's is running at
 * all), and no hit is ever queued (so a tag already loaded from a
 * public page learns nothing when the visitor moves into their
 * dashboard). The second is the one that matters on a client-side
 * navigation, and the one a loaded-once-and-forgotten tag gets wrong.
 *
 * Asserted against a fake ``window``, so the refusals are observable:
 * a refused path leaves the host object untouched — no ``dataLayer``,
 * no ``gtag`` — rather than leaving an empty queue nobody can tell
 * apart from a queue that was never consulted.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import { readFileSync } from 'node:fs'

import {
  GTAG_CONFIG,
  configureGtag,
  ensureGtag,
  gaDisableFlag,
  gtagSrc,
  measurementId,
  pageViewParams,
  sendPageView,
  setGaDisabled,
  shouldLoadGtag,
  type GtagHost,
} from './googleAnalytics.ts'
import { cspDirectives } from './securityHeaders.ts'

/** A plausible ID. Shape only — not Fresh Collective's. */
const ID = 'G-TESTID1234'
const ORIGIN = 'https://freshcollective.au'

/** A fresh fake ``window``: nothing on it until something adds it. */
function host(): GtagHost {
  return {}
}

/** ``dataLayer`` as arrays, since gtag queues ``arguments`` objects. */
function queued(h: GtagHost): unknown[][] {
  return (h.dataLayer ?? []).map((entry) =>
    Array.from(entry as ArrayLike<unknown>),
  )
}

/** Paths that must never start the tag or produce a hit. */
const NOT_TRACKABLE: readonly string[] = [
  // Signed-in surfaces
  '/dashboard',
  '/dashboard/collectives',
  '/settings',
  '/settings/notifications',
  '/profile/usr_123',
  '/notifications',
  '/messages/thr_456',
  '/onboarding',
  '/checkout',
  // Admin and creator
  '/admin',
  '/admin/collectives/moonlit-circle',
  '/creator-studio',
  '/creator-studio/pathways/slowing-down',
  '/creator',
  '/creator-onboarding',
  '/build-your-collective',
  // Tokens in the URL
  '/invites/8f3c1d9e4b7a2056',
  `/reset-password?token=${'a'.repeat(64)}`,
  `/verify-email?token=${'b'.repeat(64)}`,
  // Public but query-carrying
  '/login?next=%2Fdashboard',
  '/signup',
  '/forgot-password',
  // Private Collective areas
  '/spaces/moonlit-circle/community/cp_789',
  '/spaces/moonlit-circle/members/mem_1',
  '/spaces/moonlit-circle/events',
  // Unlisted, and the point of the sitemap change
  '/tnlbook123',
  // Never named at all
  '/some-new-page',
]

/** Paths that are on the allow-list and must work end to end. */
const TRACKABLE: readonly string[] = [
  '/',
  '/for-creators',
  '/membership',
  '/tnlbook',
  '/discover-places',
  '/discover-places/misty-harbour',
  '/spaces/moonlit-circle/about',
  '/spaces/moonlit-circle/pathways/slowing-down/about',
]

// ---------------------------------------------------------------------------
// 1 · The loader never fires on a non-trackable path
// ---------------------------------------------------------------------------

describe('the GA loader never fires on a non-trackable path', () => {
  for (const path of NOT_TRACKABLE) {
    test(`${path} loads no script`, () => {
      assert.equal(
        shouldLoadGtag(path, ID),
        false,
        `${path} would have requested gtag/js from Google`,
      )
    })

    test(`${path} queues no hit`, () => {
      // The other half, and the one that matters after a client-side
      // navigation: the tag may already be loaded from a public page.
      const h = host()
      assert.equal(sendPageView(path, ORIGIN, ID, h), false)
      assert.equal(
        h.dataLayer,
        undefined,
        `${path} touched dataLayer; a refusal must leave no trace`,
      )
      assert.equal(h.gtag, undefined)
    })
  }

  test('a tag already loaded is told nothing on the way into a member area', () => {
    // The realistic sequence, as one test: a visitor reads the
    // homepage, then signs in and opens their dashboard. The tag is
    // live and the queue exists — and it gains nothing.
    const h = host()
    assert.equal(configureGtag(ID, h, new Date(0)), true)
    assert.equal(sendPageView('/', ORIGIN, ID, h), true)
    const afterPublicPage = queued(h).length

    for (const path of ['/dashboard', '/settings', '/messages/thr_1']) {
      assert.equal(sendPageView(path, ORIGIN, ID, h), false)
    }
    assert.equal(
      queued(h).length,
      afterPublicPage,
      'a member-area navigation added something to the queue',
    )
  })

  test('the refusal is the allow-list, not a second copy of it', () => {
    // Why this file does not restate which paths are private: it
    // imports the rule. If ``isTrackablePath`` were bypassed here, the
    // two files could disagree and the tests would still pass.
    const src = readFileSync('src/lib/googleAnalytics.ts', 'utf8')
    assert.match(src, /import \{ isTrackablePath \} from '\.\/analytics\.ts'/)
    assert.equal(
      (src.match(/isTrackablePath\(/g) ?? []).length,
      3,
      'all three gates — load, disable and send — should consult the allow-list',
    )
  })
})

// ---------------------------------------------------------------------------
// 1b · The tag is switched off outright on a non-trackable path
// ---------------------------------------------------------------------------

describe("Google's opt-out flag follows the navigation", () => {
  // The gap this closes. Refusing to send a page view governs only the
  // hits we send. GA4's enhanced measurement fires ``scroll``,
  // ``click``, ``file_download``, ``form_start`` and the video events
  // from its own listeners, each stamped with ``page_location`` read
  // from the current URL — so a tag loaded on the homepage and left
  // running would report a private path on the first scroll, with no
  // page view involved. ``window['ga-disable-<id>'] = true`` is
  // Google's documented opt-out and stops the tag transmitting
  // entirely.

  const FLAG = `ga-disable-${ID}` as const

  test('the flag is named exactly as Google documents it', () => {
    // A typo here is the silent failure: the tag keeps transmitting
    // and nothing anywhere reports a problem.
    assert.equal(gaDisableFlag(ID), 'ga-disable-G-TESTID1234')
    assert.equal(gaDisableFlag(ID), FLAG)
  })

  test('navigating off a trackable path disables the tag, and back enables it', () => {
    // The sequence as a visitor performs it: homepage, into their
    // dashboard, back out to a public page.
    const h = host()

    assert.equal(setGaDisabled('/', ID, h), false)
    assert.equal(h[FLAG], false, 'the tag should be live on the homepage')

    assert.equal(setGaDisabled('/dashboard', ID, h), true)
    assert.equal(h[FLAG], true, 'the tag should be off in the dashboard')

    assert.equal(setGaDisabled('/membership', ID, h), false)
    assert.equal(h[FLAG], false, 'the tag should be live again')
  })

  test('it is set on first load too, trackable or not', () => {
    // Not only on a change: a visitor whose first page is a member
    // area must not be relying on a later navigation to switch the tag
    // off, and one who lands on a public page must not be waiting for
    // one to switch it on.
    const onPublic = host()
    setGaDisabled('/tnlbook', ID, onPublic)
    assert.equal(onPublic[FLAG], false)

    const onPrivate = host()
    setGaDisabled('/spaces/moonlit-circle/community/cp_1', ID, onPrivate)
    assert.equal(onPrivate[FLAG], true)
  })

  for (const path of NOT_TRACKABLE) {
    test(`${path} disables the tag`, () => {
      const h = host()
      assert.equal(setGaDisabled(path, ID, h), true, `${path} left GA live`)
      assert.equal(h[FLAG], true)
    })
  }

  for (const path of TRACKABLE) {
    test(`${path} leaves the tag enabled`, () => {
      // The control. Without it, a flag stuck at ``true`` would pass
      // every assertion above and measure nothing at all.
      const h = host()
      assert.equal(setGaDisabled(path, ID, h), false)
      assert.equal(h[FLAG], false)
    })
  }

  test('an unknown path disables it — fail closed', () => {
    const h = host()
    assert.equal(setGaDisabled('/some-route-added-next-week', ID, h), true)
    assert.equal(setGaDisabled(null, ID, h), true)
    assert.equal(setGaDisabled(undefined, ID, h), true)
  })

  test('the flag is keyed to the configured ID, not a fixed string', () => {
    // A measurement ID change must move the flag with it, or the
    // opt-out silently addresses a tag that no longer exists.
    const h = host()
    setGaDisabled('/dashboard', 'G-OTHERID999', h)
    assert.equal(h['ga-disable-G-OTHERID999'], true)
    assert.equal(h[FLAG], undefined)
  })

  test('with no configured ID nothing is written at all', () => {
    // There is no tag to disable, and no ID to key a flag on. Writing
    // a guessed one would be a lie about what is switched off.
    const h = host()
    assert.equal(setGaDisabled('/dashboard', undefined, h), null)
    assert.deepEqual(Object.keys(h), [])
  })
})

// ---------------------------------------------------------------------------
// 2 · With no measurement ID there is no analytics at all
// ---------------------------------------------------------------------------

describe('no measurement ID means no analytics', () => {
  for (const [label, raw] of [
    ['undefined', undefined],
    ['empty', ''],
    ['whitespace', '   '],
    ['a placeholder', 'G-XXXXXXXXXX-REPLACE-ME'],
    ['a stream id', '1234567890'],
    ['a quoted value', "'G-TESTID1234'"],
    ['a DSN pasted by mistake', 'https://k@o1.ingest.de.sentry.io/1'],
    ['a UA property', 'UA-12345-1'],
  ] as [string, string | undefined][]) {
    test(`${label} loads nothing and sends nothing`, () => {
      assert.equal(measurementId(raw), null)
      // Even on the homepage, which is as trackable as a page gets.
      assert.equal(shouldLoadGtag('/', raw), false)
      const h = host()
      assert.equal(sendPageView('/', ORIGIN, raw, h), false)
      assert.equal(configureGtag(raw, h, new Date(0)), false)
      assert.equal(h.dataLayer, undefined)
    })
  }

  test('a real-shaped ID is accepted, verbatim', () => {
    // The control: without it, a validator that rejected everything
    // would pass every assertion above.
    assert.equal(measurementId(ID), ID)
    assert.equal(measurementId(` ${ID} `), ID)
    // The newer Google tag ID form takes the same loader URL.
    assert.equal(measurementId('GT-ABCD1234'), 'GT-ABCD1234')
  })
})

// ---------------------------------------------------------------------------
// 3 · What a tracked page actually sends
// ---------------------------------------------------------------------------

describe('a tracked page sends exactly one page_view', () => {
  for (const path of TRACKABLE) {
    test(`${path} is loaded and reported`, () => {
      assert.equal(shouldLoadGtag(path, ID), true)
      const h = host()
      assert.equal(sendPageView(path, ORIGIN, ID, h), true)
      const hits = queued(h)
      assert.equal(hits.length, 1)
      assert.deepEqual(hits[0], [
        'event',
        'page_view',
        { page_path: path, page_location: `${ORIGIN}${path}` },
      ])
    })
  }

  test('the queue is in the order gtag/js drains it', () => {
    // ``js`` and ``config`` before any event, or the first page view
    // lands against an unconfigured tag and is lost.
    const h = host()
    configureGtag(ID, h, new Date(0))
    sendPageView('/', ORIGIN, ID, h)
    const hits = queued(h)
    assert.equal(hits[0][0], 'js')
    assert.deepEqual(hits[1], ['config', ID, { ...GTAG_CONFIG }])
    assert.equal(hits[2][1], 'page_view')
  })

  test('each navigation is one hit, not a cumulative one', () => {
    const h = host()
    configureGtag(ID, h, new Date(0))
    for (const path of ['/', '/membership', '/for-creators']) {
      sendPageView(path, ORIGIN, ID, h)
    }
    const events = queued(h).filter((hit) => hit[0] === 'event')
    assert.equal(events.length, 3)
    assert.deepEqual(
      events.map((hit) => (hit[2] as { page_path: string }).page_path),
      ['/', '/membership', '/for-creators'],
    )
  })
})

// ---------------------------------------------------------------------------
// 4 · No query string ever reaches Google
// ---------------------------------------------------------------------------

describe('what is sent carries no query string', () => {
  // The allow-list strips the query before matching, so a page can be
  // trackable while its URL carries something that is not. Setting
  // ``page_location`` ourselves is what stops the browser's own URL
  // being transmitted — gtag reads ``document.location`` otherwise,
  // and ``document.location`` is where ``?token=`` would be.

  test('a tracked page with a query string reports only the path', () => {
    const h = host()
    assert.equal(
      sendPageView('/for-creators?utm_source=news&utm_campaign=x', ORIGIN, ID, h),
      true,
    )
    assert.deepEqual(queued(h)[0][2], {
      page_path: '/for-creators',
      page_location: `${ORIGIN}/for-creators`,
    })
  })

  test('a fragment is dropped too', () => {
    assert.deepEqual(pageViewParams('/for-creators#why', ORIGIN), {
      page_path: '/for-creators',
      page_location: `${ORIGIN}/for-creators`,
    })
  })

  test('nothing sent anywhere contains ? or #', () => {
    const h = host()
    configureGtag(ID, h, new Date(0))
    for (const path of [
      '/?ref=newsletter',
      '/membership?plan=community',
      '/spaces/moonlit-circle/about?from=explore',
    ]) {
      sendPageView(path, ORIGIN, ID, h)
    }
    const serialised = JSON.stringify(queued(h))
    assert.ok(!serialised.includes('?'), serialised)
    assert.ok(!serialised.includes('#'), serialised)
  })

  test('an existing gtag is reused, not replaced', () => {
    // Idempotence matters because the component may re-run its
    // configuration effect: replacing ``gtag`` would orphan whatever
    // the real loader had installed.
    const h = host()
    const first = ensureGtag(h)
    assert.equal(ensureGtag(h), first)
    const queue = h.dataLayer
    ensureGtag(h)
    assert.equal(h.dataLayer, queue)
  })

  test('a trailing slash on the origin does not double up', () => {
    assert.equal(
      pageViewParams('/membership', 'https://freshcollective.au/').page_location,
      'https://freshcollective.au/membership',
    )
  })
})

// ---------------------------------------------------------------------------
// 5 · The tag configuration, pinned
// ---------------------------------------------------------------------------

describe('the tag is configured to measure pages and nothing else', () => {
  test('GA sends no page view of its own', () => {
    // GA4's "page changes based on browser history events" is off in
    // the GA admin; this is the other half of that decision. With it
    // true, GA would report every History push — including every
    // navigation into a member area — without consulting the
    // allow-list at all.
    assert.equal(GTAG_CONFIG.send_page_view, false)
  })

  test('Google Signals and ad personalisation are both off', () => {
    assert.equal(GTAG_CONFIG.allow_google_signals, false)
    assert.equal(GTAG_CONFIG.allow_ad_personalization_signals, false)
  })

  test('the configuration carries nothing else', () => {
    // An exact set, so a fourth key has to be argued for here.
    assert.deepEqual(Object.keys(GTAG_CONFIG).sort(), [
      'allow_ad_personalization_signals',
      'allow_google_signals',
      'send_page_view',
    ])
  })
})

// ---------------------------------------------------------------------------
// 6 · The script URL and the CSP agree
// ---------------------------------------------------------------------------

describe('the loader origin is the one the CSP permits', () => {
  const directives = cspDirectives(undefined)

  test('script-src names the host the loader is fetched from', () => {
    const origin = new URL(gtagSrc(ID)).origin
    assert.equal(origin, 'https://www.googletagmanager.com')
    assert.ok(
      directives['script-src'].includes(origin),
      'the loader would be blocked by the enforcing CSP',
    )
  })

  test('the collection and pixel hosts are permitted', () => {
    // A blocked beacon is the silent failure: no console anyone has
    // open, and a dashboard that simply reads zero.
    assert.ok(directives['connect-src'].includes('https://*.google-analytics.com'))
    assert.ok(directives['img-src'].includes('https://*.google-analytics.com'))
  })

  test('no advertising origin is granted', () => {
    // The CSP counterpart of the two ``allow_*: false`` settings. With
    // Signals off these are never requested, so granting them would
    // permit the one category of request this configuration exists to
    // prevent.
    //
    // Scoped to the three directives the tag fetches through, which is
    // where an Ads grant would have to appear to be any use — and not
    // to ``frame-src``, which legitimately carries ``docs.google.com``
    // and ``forms.gle`` as embed providers. Matched on the Ads hosts
    // Google's own guidance names, not on the word "google".
    for (const name of ['script-src', 'connect-src', 'img-src']) {
      for (const value of directives[name]) {
        for (const ads of [
          'doubleclick.net',
          'googlesyndication.com',
          'google.com',
        ]) {
          assert.ok(
            !value.endsWith(ads),
            `${name} grants ${value}, which only Ads features would need`,
          )
        }
      }
    }
  })

  test('the measurement ID is URL-encoded into the loader URL', () => {
    assert.equal(
      gtagSrc('G-A B'),
      'https://www.googletagmanager.com/gtag/js?id=G-A%20B',
    )
  })
})

// ---------------------------------------------------------------------------
// 7 · The component is a shell over the gates, with no second path in
// ---------------------------------------------------------------------------

describe('the mounted component adds no way around the gates', () => {
  const COMPONENT = 'src/components/analytics/GoogleAnalytics.tsx'
  const src = readFileSync(COMPONENT, 'utf8')
  const code = src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')

  test('the loader is rendered only behind the gate', () => {
    assert.match(code, /shouldLoadGtag\(pathname, GA_MEASUREMENT_ID\)/)
    assert.match(code, /if \(!id \|\| !loadable\) return null/)
  })

  test('the opt-out flag is set on every navigation, before anything else', () => {
    // Order is the property, not merely presence: the flag has to be
    // written before the tag is configured and before a page view is
    // queued, or GA's own listeners get a window in which they are
    // live on the new URL.
    const flagAt = code.indexOf('setGaDisabled(pathname, GA_MEASUREMENT_ID)')
    const configAt = code.indexOf('configureGtag(GA_MEASUREMENT_ID)')
    const viewAt = code.indexOf('sendPageView(')
    assert.ok(flagAt > 0, 'the component never sets the opt-out flag')
    assert.ok(
      flagAt < configAt && flagAt < viewAt,
      'the opt-out flag must be set before configuring and before sending',
    )
    // Keyed on ``pathname`` alone, so it re-runs on the navigations
    // where ``loadable`` is false — which are the ones that matter.
    assert.match(
      code,
      /setGaDisabled\(pathname, GA_MEASUREMENT_ID\)\s*\n\s*\}, \[pathname\]\)/,
    )
  })

  test('the page view goes through sendPageView, never through gtag directly', () => {
    assert.match(code, /sendPageView\(/)
    assert.ok(
      !/window\.gtag/.test(code),
      'calling gtag directly would bypass the allow-list check',
    )
    assert.ok(
      !/dataLayer/.test(code),
      'pushing to dataLayer directly would bypass the allow-list check',
    )
  })

  test('there is no inline configuration script to drift from the module', () => {
    // The usual GA snippet puts ``gtag('config', …)`` in an inline
    // <script>. Keeping it in the module means one definition of what
    // GA is told, and one that a test can read.
    assert.ok(
      !/dangerouslySetInnerHTML/.test(code),
      'an inline script would be a second, untested configuration',
    )
    assert.match(code, /configureGtag\(GA_MEASUREMENT_ID\)/)
  })

  test('only the loader origin is requested, via next/script', () => {
    assert.match(code, /from 'next\/script'/)
    assert.match(code, /src=\{gtagSrc\(id\)\}/)
    assert.ok(
      !/googletagmanager|google-analytics/.test(code),
      'the component should not spell a Google origin out again',
    )
  })

  test('nothing else in the app talks to GA', () => {
    // One consumer, so "which pages are reported" has one answer.
    // Checked by import rather than by grepping for ``gtag``, which
    // would match this file and the module's own comments.
    assert.match(src, /from '@\/lib\/googleAnalytics'/)
  })
})
