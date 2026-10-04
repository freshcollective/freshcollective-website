import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const PREVIEW = 'lib/waysToConnectPreview.ts'
const GATED = [
  'app/ways-to-connect/page.tsx',
  'app/messages/page.tsx',
  'app/messages/[threadId]/page.tsx',
  'components/layout/SiteShell.tsx',
  'components/layout/WorldShell.tsx',
  'app/dashboard/page.tsx',
]

describe('the preview gate', () => {
  const src = codeOnly(PREVIEW)

  test('the launch flag alone opens it for everyone', () => {
    assert.match(src, /if \(isWaysToConnectEnabled\(\)\) return true/)
  })

  test('otherwise only the Platform Owner role', () => {
    assert.match(src, /me\?\.role === 'admin'/)
  })

  test('identity comes from the session, not the request', () => {
    // Nothing a member could set: no query string, no cookie read, no
    // email comparison, no hard-coded id.
    assert.match(src, /getMe\(\)/)
    for (const smell of [
      'searchParams', 'cookies(', 'headers(', 'lindsey',
      'preview=', 'token', 'secret',
    ]) {
      assert.ok(
        !src.includes(smell),
        `the gate must not depend on ${smell}`,
      )
    }
    // An email-shaped literal, rather than any '@' — the module
    // legitimately imports from '@/lib/serverApi'.
    assert.ok(
      !/['"`][^'"`\s]+@[^'"`\s]+\.[a-z]{2,}['"`]/i.test(src),
      'the gate must not compare against an email address',
    )
  })

  test('a failed identity lookup denies rather than reveals', () => {
    assert.match(src, /\.catch\(\(\) => null\)/)
  })

  test('it is server-only', () => {
    assert.ok(!src.includes("'use client'"))
    assert.match(src, /@\/lib\/serverApi/)
  })
})

describe('every gated surface uses it', () => {
  for (const path of GATED) {
    test(`${path} defers to the shared gate`, () => {
      const src = codeOnly(path)
      assert.match(src, /waysToConnectVisible\(\)/)
    })
  }

  test('no gated surface still calls the raw flag for Ways to Connect', () => {
    for (const path of GATED) {
      const src = codeOnly(path)
      assert.ok(
        !/isWaysToConnectEnabled\(\)/.test(src),
        `${path} must not use the raw flag — the owner would be locked out`,
      )
    }
  })

  test('the pages still 404 rather than erroring when unavailable', () => {
    for (const page of GATED.slice(0, 3)) {
      assert.match(codeOnly(page), /notFound\(\)/)
    }
  })

  test('the gate is awaited, not treated as a boolean', () => {
    // `if (!waysToConnectVisible())` would be truthy for a Promise and
    // silently open the page to everybody.
    for (const page of GATED.slice(0, 3)) {
      assert.match(codeOnly(page), /await waysToConnectVisible\(\)/)
    }
  })
})

describe('the raw flag is untouched elsewhere', () => {
  test('featureFlags still reads the env var', () => {
    const src = codeOnly('lib/featureFlags.ts')
    assert.match(
      src,
      /process\.env\.NEXT_PUBLIC_WAYS_TO_CONNECT_ENABLED === 'true'/,
    )
  })

  test('the in-context Recognition lines stay on the launch flag', () => {
    // Out of scope for the preview: the owner QA list is the
    // destination, its API, messages, and the safety controls. Leaving
    // these alone keeps the change small and easy to remove.
    for (const path of [
      'components/connections/InContextRecognition.tsx',
      'components/connections/CollectiveRecognition.tsx',
    ]) {
      assert.match(codeOnly(path), /isWaysToConnectEnabled\(\)/)
    }
  })
})

describe('removability', () => {
  test('the gate lives in one small file', () => {
    assert.ok(read(PREVIEW).split('\n').length < 60)
  })

  test('it says how to remove it', () => {
    assert.match(read(PREVIEW), /To remove the preview/)
  })
})
