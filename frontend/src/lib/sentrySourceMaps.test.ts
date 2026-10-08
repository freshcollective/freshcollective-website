/**
 * Private source maps: uploaded to Sentry, served to nobody.
 *
 * Phase 4B's risk runs in two directions at once. A browser stack frame
 * has to resolve back to ``src/app/…/page.tsx:38``, which needs the
 * maps in Sentry — and no member may ever fetch a ``.map`` from
 * freshcollective.au, which needs them absent from the deployed build.
 * Both are asserted here, the second against the real built output
 * rather than against a comment claiming it.
 *
 * The third thing asserted is the boring one that breaks symbolication
 * in practice: that the release the maps are filed under is character
 * for character the release the events carry. Not a short SHA against a
 * long one, and not a second naming scheme that happens to agree today.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/sentrySourceMaps.test.ts
 */

import { strict as assert } from 'node:assert'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import {
  SENTRY_PROJECT,
  sentryBuildOptions,
  sentryUploadRelease,
  withoutTraceMetadata,
} from './sentryBuildOptions.ts'
// @ts-expect-error - Node-native import path
import { SENTRY_DATA_COLLECTION, SHARED_SENTRY_OPTIONS, sentryRelease } from './sentryRuntime.ts'

const FRONTEND = new URL('../../', import.meta.url).pathname
const SHA = '1234567890abcdef1234567890abcdef12345678'

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

/** Files under .next/static, or null when nothing has been built. */
function builtStaticFiles(): string[] | null {
  const root = `${FRONTEND}.next/static`
  if (!existsSync(root)) return null
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = `${dir}/${entry}`
      if (statSync(full).isDirectory()) walk(full)
      else out.push(full)
    }
  }
  walk(root)
  return out
}

// ---------------------------------------------------------------------------
// B + C. One release, three places
// ---------------------------------------------------------------------------

describe('the release is one string in three places', () => {
  test('a server event takes it from RENDER_GIT_COMMIT', () => {
    withEnv({ RENDER_GIT_COMMIT: SHA, NEXT_PUBLIC_RELEASE_COMMIT: undefined }, () => {
      assert.equal(sentryRelease(), SHA)
    })
  })

  test('a browser event takes it from the value next.config.ts inlined', () => {
    withEnv({ NEXT_PUBLIC_RELEASE_COMMIT: SHA, RENDER_GIT_COMMIT: undefined }, () => {
      assert.equal(sentryRelease(), SHA)
    })
  })

  test('the upload takes it from the same variable', () => {
    withEnv({ RENDER_GIT_COMMIT: SHA }, () => {
      assert.equal(sentryUploadRelease(), SHA)
      assert.equal(sentryBuildOptions().release?.name, SHA)
    })
  })

  test('all three are the identical string, not merely equal-looking', () => {
    withEnv({ RENDER_GIT_COMMIT: SHA, NEXT_PUBLIC_RELEASE_COMMIT: SHA }, () => {
      const event = sentryRelease()
      const upload = sentryBuildOptions().release?.name
      assert.equal(event, upload)
      assert.equal(event?.length, 40, 'a full SHA, not a short one')
      assert.ok(/^[0-9a-f]{40}$/.test(event ?? ''))
    })
  })

  test('no second naming scheme is consulted', () => {
    // SENTRY_RELEASE is the plugin's own fallback. Setting it must not
    // change what either side uses.
    withEnv({ RENDER_GIT_COMMIT: SHA, SENTRY_RELEASE: 'some-other-name' }, () => {
      assert.equal(sentryRelease(), SHA)
      assert.equal(sentryBuildOptions().release?.name, SHA)
    })
  })

  test('absent means absent, on both sides', () => {
    // A local build: no release for events, and nothing for the plugin
    // to file artifacts under either. Never a placeholder.
    withEnv({ RENDER_GIT_COMMIT: undefined, NEXT_PUBLIC_RELEASE_COMMIT: undefined }, () => {
      assert.equal(sentryRelease(), undefined)
      assert.equal(sentryUploadRelease(), undefined)
    })
  })
})

// ---------------------------------------------------------------------------
// A. The upload configuration
// ---------------------------------------------------------------------------

describe('the build options are the minimum for an upload', () => {
  const options = sentryBuildOptions()

  test('the project is named in source, not in a variable', () => {
    assert.equal(SENTRY_PROJECT, 'fc-web')
    assert.equal(options.project, 'fc-web')
  })

  test('the organisation comes from the build environment', () => {
    withEnv({ SENTRY_ORG: 'some-org' }, () => {
      assert.equal(sentryBuildOptions().org, 'some-org')
    })
  })

  test('source maps are deleted after upload', () => {
    assert.equal(options.sourcemaps?.deleteSourcemapsAfterUpload, true)
  })

  test('source map handling is not disabled', () => {
    // The option that would silently turn this whole phase off.
    assert.notEqual(options.sourcemaps?.disable, true)
    assert.notEqual(options.sourcemaps?.disable, 'disable-upload')
  })

  test('nothing unrelated is switched on as a side effect', () => {
    assert.equal(options.tunnelRoute, undefined, 'tunnelling is not this phase')
    assert.equal(options.buildTimeInstrumentation, false, 'span instrumentation')
    assert.equal(options.routeManifestInjection, false, 'transaction naming')
    assert.equal(options.telemetry, false)
    assert.equal(options.reactComponentAnnotation, undefined)
    assert.equal(options.widenClientFileUpload, undefined, 'dependencies are not ours')
  })

  test('the build-time module is never imported by application code', () => {
    // It reads build-only configuration. Only next.config.ts may touch
    // it, or build concerns would reach the runtime bundle.
    const importers = sourceFiles().filter(
      (f) => !f.endsWith('sentryBuildOptions.ts') &&
        /from ['"].*sentryBuildOptions/.test(readFileSync(f, 'utf8')),
    )
    assert.deepEqual(importers.map((f) => f.replace(FRONTEND, '')), [])
    assert.ok(/sentryBuildOptions/.test(read('next.config.ts')))
  })
})

// ---------------------------------------------------------------------------
// I. The upload path is wired into the build
// ---------------------------------------------------------------------------

describe('the upload path is actually wired into the build', () => {
  test('a Turbopack build generates client maps and gets a post-compile hook', async () => {
    // Behavioural, through the real wrapper. The two things the upload
    // depends on: maps being generated at all, and the SDK owning the
    // hook that uploads and then deletes them.
    const { withSentryConfig } = await import('@sentry/nextjs/config')
    withEnv({ TURBOPACK: '1', RENDER_GIT_COMMIT: SHA }, () => {
      const config = withSentryConfig({}, sentryBuildOptions()) as {
        productionBrowserSourceMaps?: boolean
        compiler?: { runAfterProductionCompile?: unknown }
      }
      assert.equal(
        config.productionBrowserSourceMaps,
        true,
        'no maps would be generated, so none could be uploaded',
      )
      assert.equal(
        typeof config.compiler?.runAfterProductionCompile,
        'function',
        'nothing would upload or delete the maps',
      )
    })
  })

  test('the release the SDK injects equals the release we configure', async () => {
    // The SDK injects its own ``_sentryRelease`` into the client bundle
    // and our ``init`` passes ``release`` explicitly. If those ever
    // disagreed, half the events would be filed under a release the
    // maps are not attached to.
    const { withSentryConfig } = await import('@sentry/nextjs/config')
    withEnv({ TURBOPACK: '1', RENDER_GIT_COMMIT: SHA }, () => {
      const config = withSentryConfig({}, sentryBuildOptions()) as {
        env?: Record<string, string>
      }
      assert.equal(config.env?._sentryRelease, SHA)
      assert.equal(config.env?._sentryRelease, sentryRelease())
    })
  })

  test('the trace metadata the wrapper adds is removed again', () => {
    // withSentryConfig sets experimental.clientTraceMetadata with no way
    // to decline, and it is not inert: every HTML response then carries
    // sentry-trace and baggage meta tags. Measured, and stripped.
    const stripped = withoutTraceMetadata({
      experimental: { clientTraceMetadata: ['baggage', 'sentry-trace'], staleTimes: {} },
    })
    assert.equal(stripped.experimental?.clientTraceMetadata, undefined)
    assert.ok('staleTimes' in (stripped.experimental ?? {}), 'our own options survive')
  })

  test('next.config.ts applies the removal to the wrapped config', () => {
    const source = code(read('next.config.ts'))
    assert.ok(/withoutTraceMetadata\(\s*withSentryConfig\(/.test(source))
  })
})

// ---------------------------------------------------------------------------
// D. The auth token
// ---------------------------------------------------------------------------

describe('the auth token is build-only and unreachable', () => {
  test('nothing in our source reads it', () => {
    // The strongest form available: the plugin reads the variable
    // itself, so the name never appears as a read anywhere we control —
    // client, server or config.
    const offenders = sourceFiles()
      .concat([`${FRONTEND}next.config.ts`])
      .filter((f) => /process\.env\.SENTRY_AUTH_TOKEN/.test(code(readFileSync(f, 'utf8'))))
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })

  test('no client module references it at all', () => {
    const clientish = sourceFiles().filter(
      (f) => f.includes('/app/') || f.includes('/components/') ||
        f.includes('instrumentation-client'),
    )
    assert.ok(clientish.length > 50, 'the client file scan found nothing')
    for (const file of clientish) {
      assert.ok(
        !readFileSync(file, 'utf8').includes('SENTRY_AUTH_TOKEN'),
        `${file.replace(FRONTEND, '')} mentions the auth token`,
      )
    }
  })

  test('runtime reporting does not depend on it', () => {
    // Revoking the token must not stop event delivery. The runtime
    // reads one variable, and it is not this one.
    const runtime = code(read('src/lib/sentryRuntime.ts'))
    assert.ok(/NEXT_PUBLIC_SENTRY_DSN/.test(runtime))
    assert.ok(!/SENTRY_AUTH_TOKEN/.test(runtime))
  })

  test('the built client bundle does not contain the name', (t) => {
    const files = builtStaticFiles()
    if (!files) {
      t.skip('no .next build present — run `npm run build` to assert this')
      return
    }
    const offenders = files.filter(
      (f) => /\.(js|css|json)$/.test(f) && readFileSync(f, 'utf8').includes('SENTRY_AUTH_TOKEN'),
    )
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })
})

// ---------------------------------------------------------------------------
// G. No publicly reachable source maps
// ---------------------------------------------------------------------------

describe('the built output exposes no source maps', () => {
  test('no .map file survives under .next/static', (t) => {
    const files = builtStaticFiles()
    if (!files) {
      t.skip('no .next build present — run `npm run build` to assert this')
      return
    }
    const maps = files.filter((f) => f.endsWith('.map'))
    assert.deepEqual(
      maps.map((f) => f.replace(FRONTEND, '')),
      [],
      'these would be served at /_next/static/… to anyone who asked',
    )
  })

  test('no emitted asset points at one', (t) => {
    // Belt to the braces: even if a map were restored by hand, nothing
    // in the shipped JS tells a browser where to look.
    const files = builtStaticFiles()
    if (!files) {
      t.skip('no .next build present')
      return
    }
    const pointing = files
      .filter((f) => /\.(js|css)$/.test(f))
      .filter((f) => /sourceMappingURL/.test(readFileSync(f, 'utf8')))
    assert.deepEqual(pointing.map((f) => f.replace(FRONTEND, '')), [])
  })

  test('browser source maps are not published by our own config either', () => {
    // The SDK turns generation on for the build; this asserts we never
    // turn on Next's *publishing* of them.
    assert.ok(!/productionBrowserSourceMaps\s*:\s*true/.test(code(read('next.config.ts'))))
  })
})

// ---------------------------------------------------------------------------
// The shape a symbolicated frame has to point at
// ---------------------------------------------------------------------------
//
// Added after the first production probe came back unsymbolicated. The
// upload was fine and every debug ID matched; the probe was aimed at
// coordinates no source map could ever cover. These assertions pin the
// two facts that made it wrong, so the next person does not have to
// rediscover them from a Sentry UI.

describe('where real code lives in an emitted chunk', () => {
  function chunks(): string[] {
    const files = builtStaticFiles()
    return (files ?? []).filter((f) => /\/chunks\/.*\.js$/.test(f))
  }

  test('every chunk carries a debug id', (t) => {
    const found = chunks()
    if (found.length === 0) {
      t.skip('no .next build present — run `npm run build` to assert this')
      return
    }
    const without = found.filter(
      (f) => !/\/\/# debugId=[0-9a-f-]+/.test(readFileSync(f, 'utf8')),
    )
    // One Turbopack runtime chunk legitimately has no module code and
    // therefore no debug id; everything else must have one, since the
    // debug id is how Sentry finds the map at all.
    assert.ok(
      without.length <= 1,
      `${without.length} chunks have no debug id: ${without.slice(0, 3).join(', ')}`,
    )
  })

  test('line 1 of a chunk is the debug-id prologue, not application code', (t) => {
    // Sentry's debug-id registration is injected as the first line of
    // every chunk. It is generated code with no original source, so the
    // map's single section starts at generated line 2 — and a frame
    // reported on line 1 can never resolve to anything.
    const found = chunks()
    if (found.length === 0) {
      t.skip('no .next build present')
      return
    }
    const sampled = found.slice(0, 20)
    for (const file of sampled) {
      const firstLine = readFileSync(file, 'utf8').split('\n')[0]
      assert.ok(
        /globalThis|_sentryDebugIds|_debugIds/.test(firstLine),
        `${file.replace(FRONTEND, '')} line 1 is not the prologue: ${firstLine.slice(0, 60)}`,
      )
    }
  })

  test('a chunk is more than one line, so a character offset is not a column', (t) => {
    // The actual mistake: ``indexOf(marker) + 1`` is an offset from the
    // start of the *file*, and the probe passed it as a column on line
    // 1. Line 1 is 284 characters long, so the coordinate did not even
    // exist.
    const found = chunks()
    if (found.length === 0) {
      t.skip('no .next build present')
      return
    }
    const withCode = found.filter((f) => readFileSync(f, 'utf8').includes('\n'))
    assert.ok(withCode.length > 0, 'no multi-line chunk found')
  })

  test('the documented probe arithmetic finds line 2 or later', (t) => {
    // This is the exact computation the production verification runbook
    // uses, asserted against the real build. If a future Turbopack
    // version changes the layout, this fails instead of a probe quietly
    // reporting an unsymbolicated frame.
    const found = chunks()
    if (found.length === 0) {
      t.skip('no .next build present')
      return
    }
    const MARKER = 'Something went wrong.'
    const located: { file: string; line: number; column: number }[] = []
    for (const file of found) {
      const text = readFileSync(file, 'utf8')
      const at = text.indexOf(MARKER)
      if (at < 0) continue
      const upTo = text.slice(0, at)
      located.push({
        file: file.replace(FRONTEND, ''),
        line: upTo.split('\n').length,
        column: at - (upTo.lastIndexOf('\n') + 1) + 1,
      })
    }
    assert.ok(located.length > 0, `no chunk contains ${MARKER}`)
    // Every one of them, not just the first: a probe picks whichever
    // chunk the page happened to load.
    const onLineOne = located.filter((l) => l.line <= 1)
    assert.deepEqual(
      onLineOne,
      [],
      'application code on line 1 cannot be symbolicated — the map starts at line 2',
    )
    for (const l of located) assert.ok(l.column > 0)
  })
})

// ---------------------------------------------------------------------------
// E + F. Phases 1–3 are untouched
// ---------------------------------------------------------------------------

describe('nothing from the earlier phases moved', () => {
  test('tracing, logs and metrics are still off', () => {
    assert.equal(SHARED_SENTRY_OPTIONS.tracesSampleRate, 0)
    assert.equal(SHARED_SENTRY_OPTIONS.beforeSendLog(), null)
    assert.equal(SHARED_SENTRY_OPTIONS.beforeSendMetric(), null)
  })

  test('no replay or profiling sampling appeared', () => {
    for (const key of ['replaysSessionSampleRate', 'replaysOnErrorSampleRate', 'profilesSampleRate']) {
      assert.ok(!(key in SHARED_SENTRY_OPTIONS), `${key} is configured`)
    }
  })

  test('the collection switches are still all off', () => {
    assert.equal(SENTRY_DATA_COLLECTION.userInfo, false)
    assert.equal(SENTRY_DATA_COLLECTION.cookies, false)
    assert.equal(SENTRY_DATA_COLLECTION.stackFrameVariables, false)
    assert.deepEqual(SENTRY_DATA_COLLECTION.httpBodies, [])
  })

  test('the scrubbers are still the ones wired in', () => {
    assert.equal(typeof SHARED_SENTRY_OPTIONS.beforeSend, 'function')
    assert.equal(typeof SHARED_SENTRY_OPTIONS.beforeBreadcrumb, 'function')
  })

  test('source context is still collected, which is the point of this phase', () => {
    // frameContextLines is what makes a symbolicated frame show code
    // rather than only a line number.
    assert.equal(SENTRY_DATA_COLLECTION.frameContextLines, 5)
  })
})

// ---------------------------------------------------------------------------
// H + the source-content audit
// ---------------------------------------------------------------------------

describe('what the maps may contain', () => {
  test('no credential-shaped literal exists in frontend source', () => {
    // Source maps carry our source. Ordinary frontend code is not
    // secret, but a hard-coded key would become Sentry's problem too.
    const patterns = [
      /sk_live_[A-Za-z0-9]/, /sk_test_[A-Za-z0-9]/, /whsec_[A-Za-z0-9]/,
      /AKIA[0-9A-Z]{16}/, /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
      /ghp_[A-Za-z0-9]{20,}/, /xox[baprs]-[A-Za-z0-9]/,
      /re_[A-Za-z0-9]{20,}/, /sntrys_[A-Za-z0-9]/,
    ]
    const offenders: string[] = []
    for (const file of sourceFiles()) {
      const text = readFileSync(file, 'utf8')
      for (const pattern of patterns) {
        if (pattern.test(text)) offenders.push(`${file.replace(FRONTEND, '')}: ${pattern}`)
      }
    }
    assert.deepEqual(offenders, [])
  })

  test('no Sentry DSN is committed outside the tests', () => {
    const offenders = sourceFiles().filter((f) => /@o\d+\.ingest\./.test(readFileSync(f, 'utf8')))
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })

  test('env files are not part of the source that could be mapped', () => {
    // A .map embeds the modules that were bundled. .env is not a module
    // and nothing imports it; stated so the question is closed.
    const offenders = sourceFiles().filter((f) =>
      /from ['"][^'"]*\.env/.test(readFileSync(f, 'utf8')),
    )
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })

  test('test files with fake credentials are not imported by the app', () => {
    // Their fake literals would otherwise be bundled, mapped and
    // uploaded. Harmless, but it would also mean test code shipping.
    const offenders = sourceFiles().filter((f) =>
      /from ['"][^'"]*\.test(\.ts)?['"]/.test(readFileSync(f, 'utf8')),
    )
    assert.deepEqual(offenders.map((f) => f.replace(FRONTEND, '')), [])
  })
})
