/**
 * The shape of the integration, pinned.
 *
 * Phase 3 is deliberately narrow — error monitoring, nothing else — and
 * most of what keeps it narrow is an absence: no Replay import, no
 * tracing integration, no tunnel, no source-map upload, no debug route.
 * Absences do not fail at runtime, so they are asserted here, against
 * the files themselves.
 *
 * Read as source rather than imported, because several of the things
 * being checked are about files that cannot be imported under
 * ``node --test`` at all: a ``.tsx`` boundary, Next's instrumentation
 * entry points, and the blueprint.
 *
 * Parsed where parsing matters. These files explain in prose why they
 * do not use Session Replay, so a substring search for "replay" finds
 * the explanation and fails — the lesson this codebase has already
 * learned once about banning a word rather than a use.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/sentryIntegration.test.ts
 */

import { strict as assert } from 'node:assert'
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs'
import { describe, test } from 'node:test'

const FRONTEND = new URL('../../', import.meta.url).pathname
const REPO = new URL('../../../', import.meta.url).pathname

function read(relative: string): string {
  return readFileSync(`${FRONTEND}${relative}`, 'utf8')
}

/** Source with comments and docstring prose removed. */
function code(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((line) => line.replace(/\/\/.*$/, ''))
    .join('\n')
}

function sourceFiles(): string[] {
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = `${dir}/${entry}`
      if (statSync(full).isDirectory()) {
        if (entry === 'node_modules' || entry === '.next') continue
        walk(full)
      } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
        out.push(full)
      }
    }
  }
  walk(`${FRONTEND}src`)
  return out
}

const INIT_FILES = ['src/instrumentation-client.ts', 'sentry.server.config.ts']

// ---------------------------------------------------------------------------
// A. Initialisation, and the no-DSN no-op
// ---------------------------------------------------------------------------

describe('both runtimes initialise the same way', () => {
  for (const file of INIT_FILES) {
    test(`${file} initialises only when a DSN is present`, () => {
      const source = code(read(file))
      assert.ok(/const dsn = sentryDsn\(\)/.test(source), 'must read the one DSN variable')
      assert.ok(/if \(dsn\) \{/.test(source), 'init must be guarded')
      assert.ok(
        source.indexOf('if (dsn)') < source.indexOf('Sentry.init('),
        'the guard must come before init, or local dev makes network calls',
      )
    })

    test(`${file} uses the shared options rather than its own`, () => {
      const source = code(read(file))
      assert.ok(/\.\.\.SHARED_SENTRY_OPTIONS/.test(source))
      assert.ok(/keepOnlyErrorMonitoring/.test(source))
    })

    test(`${file} names its runtime in a tag`, () => {
      assert.ok(/component: 'fc-web'/.test(read(file)))
    })
  }

  test('the server config is registered through instrumentation.ts', () => {
    const source = code(read('src/instrumentation.ts'))
    assert.ok(/export async function register/.test(source))
    assert.ok(/sentry\.server\.config/.test(source))
    assert.ok(
      /NEXT_RUNTIME === 'nodejs'/.test(source),
      'the Node config must not load in another runtime',
    )
  })

  test('server-component and route-handler errors are captured by the SDK hook', () => {
    const source = code(read('src/instrumentation.ts'))
    assert.ok(/export const onRequestError = Sentry\.captureRequestError/.test(source))
  })

  test('no Edge runtime exists, so no Edge config was added', () => {
    // Re-audited: no middleware file, and no route opting into Edge.
    assert.ok(!existsSync(`${FRONTEND}src/middleware.ts`))
    assert.ok(!existsSync(`${FRONTEND}middleware.ts`))
    assert.ok(!existsSync(`${FRONTEND}sentry.edge.config.ts`))
    const offenders = sourceFiles().filter((f) =>
      // ``code()`` first: ``instrumentation.ts`` explains in prose that
      // no route declares an Edge runtime, and a raw search finds that
      // sentence.
      /runtime\s*=\s*['"]edge['"]/.test(code(readFileSync(f, 'utf8'))),
    )
    assert.deepEqual(offenders, [], 'an Edge route appeared — Edge needs its own init')
  })
})

// ---------------------------------------------------------------------------
// B. Features that must stay off
// ---------------------------------------------------------------------------

describe('nothing beyond error monitoring is wired in', () => {
  const BANNED_CALLS = [
    'replayIntegration',
    'replayCanvasIntegration',
    'browserTracingIntegration',
    'browserProfilingIntegration',
    'nodeProfilingIntegration',
    'feedbackIntegration',
    'feedbackAsyncIntegration',
    'feedbackSyncIntegration',
    'nodeRuntimeMetricsIntegration',
    'metrics',
    'withProfiler',
    'useProfiler',
  ]

  for (const call of BANNED_CALLS) {
    test(`${call} is never called`, () => {
      // A call, not a mention: these modules explain in prose why
      // Session Replay and profiling are out of scope, and a substring
      // search would fail on its own explanation.
      const pattern = new RegExp(`\\b${call}\\s*\\(`)
      const offenders = sourceFiles().filter((f) => pattern.test(code(readFileSync(f, 'utf8'))))
      assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
    })
  }

  test('no replay or profiling sample rate is set anywhere', () => {
    for (const key of ['replaysSessionSampleRate', 'replaysOnErrorSampleRate', 'profilesSampleRate']) {
      const pattern = new RegExp(`${key}\\s*:`)
      const offenders = sourceFiles().filter((f) => pattern.test(code(readFileSync(f, 'utf8'))))
      assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [], `${key} is configured`)
    }
  })

  test('tunnelRoute is not enabled', () => {
    // Deliberately deferred: tunnelling hides Sentry traffic from
    // ad-blockers by routing it through our own origin, and that is a
    // decision to make on evidence, not pre-emptively.
    const offenders = sourceFiles()
      .concat([`${FRONTEND}next.config.ts`])
      .filter((f) => /tunnelRoute\s*:/.test(code(readFileSync(f, 'utf8'))))
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })
})

// ---------------------------------------------------------------------------
// C. Source maps are Phase 4
// ---------------------------------------------------------------------------

describe('source maps are not part of this phase', () => {
  test('no build wrapper was needed', () => {
    // Measured, not assumed: the build compiles, the browser SDK lands
    // in the client bundle and the DSN and release are inlined, all
    // without withSentryConfig. So it is absent rather than present and
    // disabled.
    assert.ok(!/withSentryConfig/.test(code(read('next.config.ts'))))
  })

  test('browser source maps are not published', () => {
    assert.ok(!/productionBrowserSourceMaps\s*:\s*true/.test(code(read('next.config.ts'))))
  })

  test('no upload credential is referenced or declared', () => {
    for (const key of ['SENTRY_AUTH_TOKEN', 'SENTRY_ORG', 'SENTRY_PROJECT']) {
      const offenders = sourceFiles().filter((f) => f.includes(key))
      assert.deepEqual(offenders, [])
      const blueprint = readFileSync(`${REPO}render.yaml`, 'utf8')
      assert.ok(
        !new RegExp(`key:\\s*${key}\\b`).test(blueprint),
        `${key} is declared in the blueprint — that is Phase 4`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// D. No debug surface, no committed DSN
// ---------------------------------------------------------------------------

describe('nothing was added that a stranger could reach', () => {
  test('there is no sentry debug route or page', () => {
    for (const path of ['src/app/sentry-debug', 'src/app/api/sentry-debug']) {
      assert.ok(!existsSync(`${FRONTEND}${path}`), `${path} must not exist`)
    }
    const offenders = sourceFiles().filter((f) => /sentry-debug|sentry_debug/.test(readFileSync(f, 'utf8')))
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })

  test('no DSN is committed to source', () => {
    // A DSN is a public endpoint, not a secret — but configuration
    // belongs in Render, where it can be rotated without a commit.
    const offenders = sourceFiles().filter((f) =>
      /@o\d+\.ingest\./.test(readFileSync(f, 'utf8')),
    )
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })
})

// ---------------------------------------------------------------------------
// E. The boundaries still behave like boundaries
// ---------------------------------------------------------------------------

describe('error boundaries report without changing what a member sees', () => {
  test('the route boundary captures in an effect, once', () => {
    const source = read('src/app/error.tsx')
    assert.ok(/useEffect\(\(\) => \{/.test(source))
    assert.ok(/captureBoundaryError\(error, 'route'\)/.test(source))
    assert.ok(
      source.indexOf('captureBoundaryError') > source.indexOf('useEffect'),
      'capturing during render would file the same error on every re-render',
    )
    assert.ok(/\}, \[error\]\)/.test(source), 'the effect must be keyed on the error')
  })

  test('the route boundary keeps its reset and its way out', () => {
    const source = read('src/app/error.tsx')
    assert.ok(/onClick=\{reset\}/.test(source), 'Try again must still work')
    assert.ok(/Something went wrong\./.test(source))
    assert.ok(/Back to home/.test(source))
    assert.ok(/error\?\.digest/.test(source), 'the reference shown to members must stay')
  })

  test('the global boundary captures in an effect, at fatal', () => {
    const source = read('src/app/global-error.tsx')
    assert.ok(/useEffect/.test(source))
    assert.ok(/captureBoundaryError\(error, 'global'\)/.test(source))
  })

  test('the global boundary still renders its own document', () => {
    // It is the root layout's replacement; without html/body it renders
    // nothing at all.
    const source = read('src/app/global-error.tsx')
    assert.ok(/<html lang="en">/.test(source))
    assert.ok(/<body/.test(source))
    assert.ok(/onClick=\{reset\}/.test(source))
  })

  test('neither boundary attaches props or member data', () => {
    for (const file of ['src/app/error.tsx', 'src/app/global-error.tsx']) {
      const source = code(read(file))
      assert.ok(!/setUser|setExtra\(/.test(source), `${file} must not enrich the event`)
    }
  })
})

// ---------------------------------------------------------------------------
// F. The BFF reports only what it cannot answer
// ---------------------------------------------------------------------------

describe('the BFF proxy', () => {
  const source = read('src/app/api/[...path]/route.ts')

  test('reports only from the catch branch', () => {
    // A backend that answers — 401, 404, 422, its own 500 — is returned
    // untouched and is fc-api's business. Only an unreachable backend
    // is a proxy failure.
    const catchAt = source.indexOf('} catch (err: unknown) {')
    assert.ok(catchAt > 0, 'the catch branch moved')
    const before = source.slice(0, catchAt)
    assert.ok(
      !/captureProxyFailure\(/.test(code(before)),
      'the success path must not report',
    )
  })

  test('reports once, for either kind of failure', () => {
    const calls = code(source).match(/captureProxyFailure\(/g) ?? []
    assert.equal(calls.length, 1, 'one call, classified — not one per branch')
    assert.ok(/classifyProxyFailure\(err\)/.test(source))
  })

  test('the responses are unchanged', () => {
    assert.ok(/jsonResponse\(504, \{/.test(source))
    assert.ok(/jsonResponse\(502, \{/.test(source))
    assert.ok(/detail: 'The backend took too long to respond\.'/.test(source))
    assert.ok(/detail: 'Unable to reach the backend\.'/.test(source))
  })

  test('nothing sensitive is handed to the reporter', () => {
    const call = source.slice(
      source.indexOf('captureProxyFailure('),
      source.indexOf('captureProxyFailure(') + 300,
    )
    for (const forbidden of ['cookie', 'headers', 'body', 'targetUrl', 'search']) {
      assert.ok(!call.includes(forbidden), `${forbidden} must not be reported`)
    }
    assert.ok(call.includes('path: joined'), 'the application path is the identifier')
  })

  test('it still refuses webhook and internal paths', () => {
    assert.ok(/DENIED_PATH_PREFIXES: readonly string\[\] = \['webhooks', 'internal'\]/.test(source))
  })
})

// ---------------------------------------------------------------------------
// G. Degraded surfaces
// ---------------------------------------------------------------------------

describe('silent degradation', () => {
  const CAPTURED = [
    ['src/app/dashboard/page.tsx', 'dashboard'],
    ['src/app/creator-studio/offers/page.tsx', 'creator-offers'],
    ['src/app/creator-studio/offers/[offerSlug]/page.tsx', 'creator-offer-editor'],
    ['src/app/creator-studio/gathering-series/[seriesSlug]/page.tsx', 'creator-gathering-series'],
    ['src/app/creator-studio/library/page.tsx', 'creator-library'],
    ['src/app/creator-studio/settings/page.tsx', 'creator-settings'],
    ['src/app/creator/spaces/[slug]/events/[eventId]/page.tsx', 'creator-event-editor'],
    ['src/app/creator-studio/layout.tsx', 'creator-studio-layout'],
  ]

  for (const [file, surface] of CAPTURED) {
    test(`${surface} reports when its data fetch throws`, () => {
      const source = read(file)
      assert.ok(
        source.includes(`captureDegradedSurface(err, '${surface}'`),
        `${file} should tag itself ${surface}`,
      )
    })
  }

  test('the contained render boundary reports its own failure', () => {
    const source = read('src/app/creator-studio/assets/CollectiveHomePanelSafe.tsx')
    assert.ok(/componentDidCatch/.test(source))
    assert.ok(/degraded_surface: 'creator-collective-home-panel'/.test(source))
  })

  test('every surface tag is distinct', () => {
    const surfaces = CAPTURED.map(([, s]) => s)
    assert.equal(new Set(surfaces).size, surfaces.length)
  })

  test('no capture attaches a response payload', () => {
    // The helper drops non-primitives, but a call site that tried would
    // still be a misunderstanding worth catching here.
    for (const [file] of CAPTURED) {
      const source = code(read(file))
      const calls = source.match(/captureDegradedSurface\([^)]*\)/g) ?? []
      for (const call of calls) {
        assert.ok(!/\bdata\b|\bres\b|\bbody\b|\bjson\b/.test(call), `${file}: ${call}`)
      }
    }
  })

  test('deliberately swallowed promises were left alone', () => {
    // Audited and judged ignorable: a best-effort logout whose outcome
    // does not change what the member sees, a mark-as-read that the
    // next visit retries, and picker fetches that already degrade to an
    // empty list by design. Reporting those would be noise, and an
    // event per mount on a flaky connection is worse than silence.
    const logout = read('src/components/layout/LogoutButton.tsx')
    assert.ok(/\.catch\(\(\) => \{\}\)/.test(logout), 'left as it was')
    const thread = read('src/app/spaces/[slug]/messages/[threadId]/MessageThreadClient.tsx')
    assert.ok(/\.catch\(\(\) => \{\}\)/.test(thread), 'left as it was')
  })
})

// ---------------------------------------------------------------------------
// G2. The one-off verification script
// ---------------------------------------------------------------------------

describe('the server smoke-test script', () => {
  const source = read('scripts/sentry-smoke-test.ts')

  test('uses only fake credentials, on a TLD that cannot resolve', () => {
    assert.ok(/example\.invalid/.test(source))
    assert.ok(/FAKE_/.test(source))
  })

  test('reads no secret from the environment', () => {
    // It needs the DSN, and reports the environment and release. Those
    // are the only three, and the first comes through ``sentryDsn()``
    // rather than a direct read.
    const reads = [...code(source).matchAll(/process\.env\.(\w+)/g)].map((m) => m[1])
    assert.deepEqual([...new Set(reads)], [])
  })

  test('it uses the real shared options, not a copy', () => {
    // A script that configured its own options could pass while the app
    // was misconfigured.
    assert.ok(/\.\.\.SHARED_SENTRY_OPTIONS/.test(code(source)))
    assert.ok(/keepOnlyErrorMonitoring/.test(code(source)))
  })

  test('it is not scheduled, not built and not imported by the app', () => {
    const blueprint = readFileSync(`${REPO}render.yaml`, 'utf8')
    assert.ok(!blueprint.includes('sentry-smoke-test'))
    const offenders = sourceFiles().filter((f) =>
      readFileSync(f, 'utf8').includes('sentry-smoke-test'),
    )
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })

  test('it refuses to run without a DSN', () => {
    assert.ok(/if \(!dsn\) \{/.test(code(source)))
    assert.ok(/return 1/.test(code(source)))
  })
})

// ---------------------------------------------------------------------------
// H. The blueprint
// ---------------------------------------------------------------------------

describe('render.yaml', () => {
  const blueprint = readFileSync(`${REPO}render.yaml`, 'utf8')

  /**
   * fc-web's own block.
   *
   * Bounded by the next ``- type:`` rather than by the next service
   * name: fc-web's env wires two variables ``fromService: name:
   * fc-api``, so slicing at that name truncates the block before the
   * interesting part and the test passes by reading nothing.
   */
  function fcWebBlock(): string {
    const start = blueprint.indexOf('name: fc-web')
    const end = blueprint.indexOf('\n  - type:', start)
    assert.ok(start > 0 && end > start, 'the fc-web block moved')
    return blueprint.slice(start, end)
  }

  test('fc-web declares exactly one Sentry variable', () => {
    const keys = [...fcWebBlock().matchAll(/key: (\w+)/g)]
      .map((m) => m[1])
      .filter((k) => k.includes('SENTRY'))
    assert.deepEqual(keys, ['NEXT_PUBLIC_SENTRY_DSN'])
  })

  test('fc-web is not given the server-side variable name as well', () => {
    // One value to rotate, and one place it is read from.
    assert.ok(!/key: SENTRY_DSN\b/.test(fcWebBlock()))
  })

  test('its value is operator-supplied and uncommitted', () => {
    const entry = blueprint.slice(
      blueprint.indexOf('key: NEXT_PUBLIC_SENTRY_DSN'),
      blueprint.indexOf('key: NEXT_PUBLIC_SENTRY_DSN') + 120,
    )
    assert.ok(/sync: false/.test(entry))
    assert.ok(!/value:/.test(entry), 'a DSN must not be committed')
  })

  test('no environment or release variable was added', () => {
    const declared = [...blueprint.matchAll(/key: (SENTRY_\w+)/g)].map((m) => m[1])
    for (const key of ['SENTRY_ENVIRONMENT', 'SENTRY_RELEASE']) {
      assert.ok(!declared.includes(key), `${key} must be derived, not declared`)
    }
  })

  test('nothing outside fc-web was touched for this phase', () => {
    // fc-api and the seven crons keep their own server-side SENTRY_DSN
    // from Phases 1 and 2. The frontend deploy must not need theirs.
    const occurrences = (blueprint.match(/key: SENTRY_DSN/g) ?? []).length
    assert.equal(occurrences, 8, 'fc-api plus seven crons, unchanged')
  })
})
