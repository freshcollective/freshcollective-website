/**
 * The options themselves: what is collected, and what is off.
 *
 * Two things are asserted here that no leak test could catch.
 *
 * The first is that ``dataCollection`` is set *completely*. In SDK v11
 * ``sendDefaultPii`` no longer exists, and every field of its
 * replacement defaults to **collecting** — user info, cookies, headers,
 * bodies, and the local variables of whatever threw. An omitted field
 * is not a default, it is a yes. So one test reads the SDK's own type
 * definition and fails if the SDK has grown a field this app has not
 * decided about.
 *
 * The second is that error monitoring is all that is enabled, which is
 * easy to assert for today's SDK and worth asserting for tomorrow's: a
 * default integration added in a minor release should not be able to
 * start sending performance data from a production deploy.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/sentryRuntime.test.ts
 */

import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import {
  SENTRY_DATA_COLLECTION,
  SHARED_SENTRY_OPTIONS,
  isErrorMonitoringIntegration,
  keepOnlyErrorMonitoring,
  sentryDsn,
  sentryEnvironment,
  sentryRelease,
} from './sentryRuntime.ts'

const FRONTEND = new URL('../../', import.meta.url).pathname

function withEnv(values: Record<string, string | undefined>, run: () => void): void {
  const previous: Record<string, string | undefined> = {}
  for (const [key, value] of Object.entries(values)) {
    previous[key] = process.env[key]
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  try {
    run()
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }
}

// ---------------------------------------------------------------------------
// A. The DSN, and the absence of one
// ---------------------------------------------------------------------------

describe('the DSN is one variable for both runtimes', () => {
  test('it is read from NEXT_PUBLIC_SENTRY_DSN', () => {
    withEnv({ NEXT_PUBLIC_SENTRY_DSN: 'https://k@o1.ingest.de.sentry.io/1' }, () => {
      assert.equal(sentryDsn(), 'https://k@o1.ingest.de.sentry.io/1')
    })
  })

  test('absent is an empty string, which every init treats as off', () => {
    withEnv({ NEXT_PUBLIC_SENTRY_DSN: undefined }, () => {
      assert.equal(sentryDsn(), '')
    })
  })

  for (const blank of ['', '   ', '\n']) {
    test(`a blank value is also off: ${JSON.stringify(blank)}`, () => {
      withEnv({ NEXT_PUBLIC_SENTRY_DSN: blank }, () => {
        assert.equal(sentryDsn(), '')
      })
    })
  }

  test('a second server-only variable is deliberately not consulted', () => {
    // One value to rotate. A SENTRY_DSN that silently took precedence
    // on the server would make the two runtimes able to disagree.
    withEnv(
      { NEXT_PUBLIC_SENTRY_DSN: undefined, SENTRY_DSN: 'https://k@o1.ingest.de.sentry.io/9' },
      () => {
        assert.equal(sentryDsn(), '')
      },
    )
  })
})

// ---------------------------------------------------------------------------
// Environment and release, both derived
// ---------------------------------------------------------------------------

describe('environment is derived, not declared', () => {
  test('production when NODE_ENV says so', () => {
    withEnv({ NODE_ENV: 'production' }, () => {
      assert.equal(sentryEnvironment(), 'production')
    })
  })

  for (const value of ['development', 'test', undefined]) {
    test(`anything else is development: ${value}`, () => {
      withEnv({ NODE_ENV: value }, () => {
        assert.equal(sentryEnvironment(), 'development')
      })
    })
  }
})

describe('release is derived from the deploy, or absent', () => {
  const SHA = '1234567890abcdef1234567890abcdef12345678'

  test('the server reads Render’s own variable', () => {
    withEnv({ RENDER_GIT_COMMIT: SHA, NEXT_PUBLIC_RELEASE_COMMIT: undefined }, () => {
      assert.equal(sentryRelease(), SHA)
    })
  })

  test('the browser reads the value next.config.ts inlined', () => {
    withEnv({ NEXT_PUBLIC_RELEASE_COMMIT: SHA, RENDER_GIT_COMMIT: undefined }, () => {
      assert.equal(sentryRelease(), SHA)
    })
  })

  test('absent means undefined, never a placeholder', () => {
    // "unknown" looks like a version and groups every deploy together.
    withEnv({ NEXT_PUBLIC_RELEASE_COMMIT: undefined, RENDER_GIT_COMMIT: undefined }, () => {
      assert.equal(sentryRelease(), undefined)
    })
  })

  test('an empty inlined value is treated as absent, not as a release', () => {
    // What a local build produces: next.config.ts maps an unset
    // RENDER_GIT_COMMIT to ''.
    withEnv({ NEXT_PUBLIC_RELEASE_COMMIT: '', RENDER_GIT_COMMIT: undefined }, () => {
      assert.equal(sentryRelease(), undefined)
    })
  })
})

// ---------------------------------------------------------------------------
// dataCollection — the replacement for sendDefaultPii
// ---------------------------------------------------------------------------

describe('dataCollection refuses every category of member data', () => {
  test('no user enrichment: no address, no username, no IP', () => {
    assert.equal(SENTRY_DATA_COLLECTION.userInfo, false)
  })

  test('no cookies — the session lives on this origin', () => {
    assert.equal(SENTRY_DATA_COLLECTION.cookies, false)
  })

  test('no headers in either direction', () => {
    assert.deepEqual(SENTRY_DATA_COLLECTION.httpHeaders, { request: false, response: false })
  })

  test('no request or response bodies', () => {
    assert.deepEqual(SENTRY_DATA_COLLECTION.httpBodies, [])
  })

  test('no frame locals — the default most likely to hold a raw token', () => {
    assert.equal(SENTRY_DATA_COLLECTION.stackFrameVariables, false)
  })

  test('no database query data, no queue arguments', () => {
    assert.equal(SENTRY_DATA_COLLECTION.databaseQueryData, false)
    assert.equal(SENTRY_DATA_COLLECTION.queues, false)
  })

  test('no gen-AI inputs or outputs', () => {
    assert.deepEqual(SENTRY_DATA_COLLECTION.genAI, { inputs: false, outputs: false })
  })

  test('no GraphQL documents or variables', () => {
    assert.deepEqual(SENTRY_DATA_COLLECTION.graphQL, { document: false, variables: false })
  })

  test('query parameters are filtered rather than dropped', () => {
    // Keeping ``?tab=settings`` is the difference between an issue you
    // can act on and a route name. The credential-bearing names are
    // denied here and redacted again by scrubEvent.
    const behaviour = SENTRY_DATA_COLLECTION.urlQueryParams as { deny: string[] }
    assert.ok(Array.isArray(behaviour.deny))
    for (const param of ['token', 'reset_token', 'claim_token', 'code', 'email']) {
      assert.ok(behaviour.deny.includes(param), `${param} must be denied`)
    }
  })

  test('our own source context lines are kept, deliberately', () => {
    // Not member data, and the difference between a readable stack and
    // a line number. Stated rather than left to the default.
    assert.equal(SENTRY_DATA_COLLECTION.frameContextLines, 5)
  })

  test('every field the SDK offers has been decided about', () => {
    // The guard that matters most. An omitted field does not inherit a
    // safe default — it inherits "collect it" — so an SDK upgrade that
    // adds a category must fail here rather than start sending.
    const types = readFileSync(
      `${FRONTEND}node_modules/@sentry/core/build/types/types/datacollection.d.ts`,
      'utf8',
    )
    const body = types.slice(types.indexOf('export interface DataCollection {'))
    const fields = [...body.matchAll(/^\s{4}(\w+)\?:/gm)].map((m) => m[1])
    assert.ok(fields.length >= 10, `only found ${fields.length} fields to check`)
    const decided = Object.keys(SENTRY_DATA_COLLECTION)
    const missing = fields.filter((f) => !decided.includes(f))
    assert.deepEqual(
      missing,
      [],
      `the SDK collects these by default and nothing here says otherwise: ${missing.join(', ')}`,
    )
  })

  test('sendDefaultPii is not used, because it no longer exists', () => {
    // Kept as a statement rather than a comment: if a future SDK
    // reintroduces it, this is where the decision gets revisited.
    const options = readFileSync(
      `${FRONTEND}node_modules/@sentry/core/build/types/types/options.d.ts`,
      'utf8',
    )
    assert.ok(
      !/^\s+sendDefaultPii\??:/m.test(options),
      'sendDefaultPii is back in the SDK — revisit the dataCollection block',
    )
  })
})

// ---------------------------------------------------------------------------
// Error monitoring only
// ---------------------------------------------------------------------------

describe('nothing but error monitoring is enabled', () => {
  test('tracing is off at the sample rate', () => {
    assert.equal(SHARED_SENTRY_OPTIONS.tracesSampleRate, 0)
  })

  test('and again by pattern, so a stray span cannot escape', () => {
    // ``beforeSendTransaction`` is deliberately not used: v11 streams
    // spans by default and ignores that hook, warning about it on every
    // boot. ``ignoreSpans`` is the mechanism that still applies.
    const patterns = SHARED_SENTRY_OPTIONS.ignoreSpans as RegExp[]
    assert.equal(patterns.length, 1)
    assert.ok(patterns[0].test('any span name at all'))
  })

  test('the hook the SDK ignores is not used', () => {
    assert.ok(
      !('beforeSendTransaction' in SHARED_SENTRY_OPTIONS),
      'beforeSendTransaction is ignored with streamed spans and warns on boot',
    )
  })

  test('the logs product is refused', () => {
    assert.equal(SHARED_SENTRY_OPTIONS.beforeSendLog(), null)
  })

  test('the metrics product is refused', () => {
    assert.equal(SHARED_SENTRY_OPTIONS.beforeSendMetric(), null)
  })

  test('no replay sampling is configured at all', () => {
    const keys = Object.keys(SHARED_SENTRY_OPTIONS)
    for (const banned of ['replaysSessionSampleRate', 'replaysOnErrorSampleRate', 'profilesSampleRate']) {
      assert.ok(!keys.includes(banned), `${banned} must not be configured`)
    }
  })

  test('the breadcrumb trail is bounded', () => {
    assert.equal(SHARED_SENTRY_OPTIONS.maxBreadcrumbs, 30)
  })

  for (const name of [
    'BrowserTracing', 'Replay', 'ReplayCanvas', 'BrowserProfiling',
    'NodeProfiling', 'Feedback', 'BrowserSession', 'ProcessSession',
    'ConversationId', 'LocalVariablesAsync', 'NodeRuntimeMetrics',
  ]) {
    test(`${name} is filtered out of the defaults`, () => {
      assert.equal(isErrorMonitoringIntegration(name), false)
    })
  }

  for (const name of [
    'Breadcrumbs', 'BrowserApiErrors', 'Console', 'Dedupe', 'EventFilters',
    'FunctionToString', 'GlobalHandlers', 'HttpContext', 'LinkedErrors',
    'ContextLines', 'Http', 'OnUncaughtException', 'OnUnhandledRejection',
    'RequestData', 'Modules', 'NodeFetch',
  ]) {
    test(`${name} is kept — it is how errors are caught or described`, () => {
      assert.equal(isErrorMonitoringIntegration(name), true)
    })
  }

  test('the filter is applied to a list, not to one name at a time', () => {
    const kept = keepOnlyErrorMonitoring([
      { name: 'GlobalHandlers' },
      { name: 'Replay' },
      { name: 'LinkedErrors' },
      { name: 'BrowserTracing' },
    ])
    assert.deepEqual(kept.map((i: { name: string }) => i.name), ['GlobalHandlers', 'LinkedErrors'])
  })
})
