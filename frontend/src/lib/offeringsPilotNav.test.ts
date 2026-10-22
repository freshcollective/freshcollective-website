import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { browserApiPath } from './api.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/**
 * Both defects fixed here are explained at length in the source, and
 * the explanations quote the broken code on purpose. A raw substring
 * check would match the explanation and pass vacuously, so every
 * assertion below runs against comment-stripped source.
 */
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const SIDEBAR = 'app/creator-studio/CreatorStudioSidebar.tsx'
const SHELL = 'app/creator-studio/CreatorStudioShell.tsx'
const LAYOUT = 'app/creator-studio/layout.tsx'
const GUARD = 'lib/offeringsAccess.ts'
const OFFERINGS_LAYOUT = 'app/creator-studio/offerings/layout.tsx'
const ABOUT_PAGE = 'app/creator-studio/offerings/[offeringSlug]/about/page.tsx'
const EDITOR = 'app/creator-studio/pathways/[pathwaySlug]/AboutPageEditor.tsx'

/** Every .tsx under src/app that is NOT a client component. */
function serverComponents(): string[] {
  const out: string[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) {
        walk(full)
      } else if (entry.endsWith('.tsx')) {
        const src = readFileSync(full, 'utf8')
        if (!/^\s*['"]use client['"]/m.test(src.split('\n').slice(0, 3).join('\n'))) {
          out.push(relative(SRC, full))
        }
      }
    }
  }
  walk(join(SRC, 'app'))
  return out
}

// ---------------------------------------------------------------------------
// Issue 1 — Creator Studio navigation must respect the pilot
// ---------------------------------------------------------------------------

describe('Creator Studio hides Offerings outside the pilot', () => {
  test('the Offerings nav item is pilot-gated', () => {
    const line = codeOnly(SIDEBAR)
      .split('\n')
      .find((l) => l.includes("href: '/creator-studio/offerings'"))
    assert.ok(line, 'no nav entry for /creator-studio/offerings')
    assert.match(
      line,
      /requiresOfferings: true/,
      'Offerings must be hidden for Collectives outside the pilot',
    )
  })

  test('the pilot gate is separate from the plan gate', () => {
    // Two different questions: a plan capability is the same answer for
    // every Collective a creator owns, the pilot changes between them.
    // Collapsing them would make the pilot look like a billing tier.
    const src = codeOnly(SIDEBAR)
    assert.match(src, /\(\{ requiresOfferings \}\) =>\s*!requiresOfferings \|\| offeringsAvailable/)
    const offeringsLine = src
      .split('\n')
      .find((l) => l.includes("href: '/creator-studio/offerings'"))!
    assert.doesNotMatch(
      offeringsLine,
      /requiresPaidOffers/,
      'the pilot is not a plan tier',
    )
  })

  test('Pathways and Gatherings are NOT pilot-gated', () => {
    const src = codeOnly(SIDEBAR)
    for (const href of ['/creator-studio/pathways', '/creator-studio/gatherings']) {
      const line = src.split('\n').find((l) => l.includes(`href: '${href}'`))
      assert.ok(line, `no nav entry for ${href}`)
      assert.doesNotMatch(
        line,
        /requiresOfferings/,
        `${href} must not be affected by the Offerings pilot`,
      )
    }
  })

  test('the flag is threaded from the layout through the shell', () => {
    assert.match(codeOnly(LAYOUT), /offeringsAvailable=\{offeringsAvailable\}/)
    assert.match(codeOnly(SHELL), /offeringsAvailable=\{offeringsAvailable\}/)
    assert.match(codeOnly(SIDEBAR), /offeringsAvailable = false/)
  })

  test('eligibility comes from the server, and defaults to hidden', () => {
    const src = codeOnly(LAYOUT)
    assert.match(src, /let offeringsAvailable = false/,
      'must default to hidden so a failed fetch cannot expose the surface')
    assert.match(src, /detail\?\.offerings_available === true/,
      'must read the backend field, strictly')
  })

  test('navigation re-answers per Collective rather than once per session', () => {
    // The layout resolves it from the ACTIVE space's detail payload, so
    // switching Collectives (which changes the active-space cookie)
    // re-fetches with the new slug on the next navigation.
    const src = codeOnly(LAYOUT)
    assert.match(src, /getCreatorSpace\(activeSpace\.slug\)/)
    const idx = src.indexOf('offerings_available')
    const spaceIdx = src.indexOf('getCreatorSpace(activeSpace.slug)')
    assert.ok(spaceIdx !== -1 && idx > spaceIdx,
      'eligibility must be read off the active Collective, not a global')
  })

  const PILOT_FILES = [SIDEBAR, SHELL, LAYOUT, GUARD, OFFERINGS_LAYOUT]

  test('no Collective identifier is hardcoded in the frontend', () => {
    // Raw text, not codeOnly, and deliberately so: a specific
    // Collective's id or slug would be just as wrong sitting in a
    // comment that a later edit could uncomment. There is no
    // legitimate reason for either to appear in client code at all.
    for (const file of PILOT_FILES) {
      const src = read(file)
      for (const needle of [
        'a08c3147-ae1c-4a4c-94e1-96059cc95bb2',
        'moonlit-circle',
      ]) {
        assert.ok(
          !src.includes(needle),
          `${file} must not name a pilot Collective — eligibility is the backend's answer`,
        )
      }
    }
  })

  test('no frontend allow-list or build-time Offerings flag exists', () => {
    // codeOnly here, not raw text: ``offeringsAccess.ts`` *explains*
    // that the backend resolves OFFERINGS_PILOT_COLLECTIVES, and that
    // sentence is the documentation this convention needs. What must
    // not exist is frontend code reading a flag or holding a list —
    // a second source of truth that drifts the first time the pilot
    // changes. So: ban the use, not the word.
    for (const file of PILOT_FILES) {
      const src = codeOnly(file)
      for (const needle of [
        'OFFERINGS_PILOT_COLLECTIVES',
        'NEXT_PUBLIC_OFFERINGS',
        'offerings_pilot',
      ]) {
        assert.ok(
          !src.includes(needle),
          `${file} must not read ${needle} — the pilot is resolved server-side`,
        )
      }
      assert.ok(
        !/process\.env\.[A-Z_]*OFFERING/.test(src),
        `${file} must not gate Offerings on a build-time env var`,
      )
    }
  })

  test('direct navigation is refused by one layout, not six page checks', () => {
    const src = codeOnly(OFFERINGS_LAYOUT)
    assert.match(src, /requireOfferingsAvailable\(\)/)
    // The guard 404s, matching require_pilot_space, rather than
    // redirecting or rendering an upgrade notice — a refusal must not
    // confirm the feature exists.
    assert.match(codeOnly(GUARD), /notFound\(\)/)
  })
})

// ---------------------------------------------------------------------------
// Issue 2 — apiUrl must not cross the server/client boundary
// ---------------------------------------------------------------------------

describe('browserApiPath forces a browser fetch same-origin', () => {
  test('an absolute internal URL is reduced to its path', () => {
    // This is the production shape: Render's private host:port.
    assert.equal(
      browserApiPath('http://fc-api-2gzj:10000/api/creator/spaces/x/offerings/y/about-blocks'),
      '/api/creator/spaces/x/offerings/y/about-blocks',
    )
  })

  test('the local-dev shape is reduced too', () => {
    // The shape that made this bug invisible in development: a dev
    // browser CAN reach localhost:8000, so the editor worked locally.
    assert.equal(
      browserApiPath('http://localhost:8000/api/creator/spaces/x/about-blocks'),
      '/api/creator/spaces/x/about-blocks',
    )
  })

  test('https and a port are handled', () => {
    assert.equal(browserApiPath('https://api.example.test:8443/api/a/b'), '/api/a/b')
  })

  test('a path passes through unchanged', () => {
    assert.equal(browserApiPath('/api/creator/spaces/x/about-blocks'), '/api/creator/spaces/x/about-blocks')
  })

  test('it is idempotent', () => {
    const once = browserApiPath('http://fc-api:10000/api/a')
    assert.equal(browserApiPath(once), once)
  })

  test('query strings and fragments survive', () => {
    assert.equal(browserApiPath('http://fc-api:10000/api/a?b=1&c=2'), '/api/a?b=1&c=2')
  })
})

describe('no server component hands apiUrl across the boundary', () => {
  test('apiUrl() is never passed as a prop from a server component', () => {
    // The whole class of bug, not just the one instance. A server
    // component that computes apiUrl() and passes it to a client
    // component gives the browser an unreachable private host.
    const offenders: string[] = []
    for (const file of serverComponents()) {
      const src = codeOnly(file)
      if (/\w+=\{apiUrl\(/.test(src)) offenders.push(file)
    }
    assert.deepEqual(
      offenders, [],
      'these server components pass apiUrl() into a client component; '
      + 'pass the path and let the client resolve it',
    )
  })

  test('the Offering About page passes a path, not a resolved URL', () => {
    const src = codeOnly(ABOUT_PAGE)
    assert.doesNotMatch(src, /blocksApiUrl=\{apiUrl\(/)
    assert.match(src, /blocksApiUrl=\{\s*`\/api\/creator\/spaces\//)
  })

  test('the editor normalises whatever it is given', () => {
    // Belt and braces: even if a caller resolves the URL, the fetches
    // stay same-origin.
    assert.match(codeOnly(EDITOR), /browserApiPath\(blocksApiUrl \?\?/)
  })

  test('every block operation derives from the normalised URL', () => {
    // add / edit / delete / reorder were ALL broken, not just add.
    const src = codeOnly(EDITOR)
    assert.match(src, /fetch\(blocksUrl,/)
    assert.match(src, /fetch\(`\$\{blocksUrl\}\/\$\{blockId\}`/)
    assert.match(src, /fetch\(`\$\{blocksUrl\}\/reorder`/)
    // No fetch in this component may bypass it.
    const bare = src.match(/fetch\(\s*apiUrl\(/g) ?? []
    assert.deepEqual(bare, [], 'block fetches must go through blocksUrl')
  })
})
