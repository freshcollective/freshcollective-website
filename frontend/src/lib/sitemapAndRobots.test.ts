/**
 * What Fresh Collective invites a crawler to read.
 *
 * A sitemap is an invitation, so the failures that matter here are
 * the ones that publish something: a signed-in surface offered for
 * indexing, a private Collective named in a public file, a path
 * disallowed so broadly that the public pages go with it.
 *
 * These are source-contract tests. The route handlers are server
 * modules that fetch at request time, so what is pinned is the shape
 * of the decision — which pages are offered, which paths are closed,
 * where the Collective list comes from — rather than a rendered XML
 * body. The data side is covered by the backend's own
 * ``test_public_sitemap_source.py``, which is where visibility is
 * actually decided.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const read = (p: string) => readFileSync(join(ROOT, p), 'utf8')
const withoutDocComments = (src: string) => src.replace(/\/\*\*[\s\S]*?\*\//g, '')

/**
 * Strip every comment before reading string literals out of source.
 *
 * Not fastidiousness: the word "member's" in a robots.ts comment put
 * an odd number of apostrophes in the file, and a naive scan for
 * ``'...'`` then paired the quotes across it and returned the gaps
 * between the real entries rather than the entries.
 */
const codeOnly = (src: string) =>
  withoutDocComments(src).replace(/\/\/[^\n]*/g, '')

const literalsIn = (block: string) =>
  [...block.matchAll(/'([^']+)'/g)].map((m) => m[1])

const SITEMAP = 'src/app/sitemap.ts'
const ROBOTS = 'src/app/robots.ts'

/** The pages the sitemap offers, read from its own list. */
function publicPages(): string[] {
  const block = /const PUBLIC_PAGES = \[([\s\S]*?)\] as const/.exec(
    codeOnly(read(SITEMAP)),
  )
  assert.ok(block, 'PUBLIC_PAGES should be declared as a list')
  return literalsIn(block[1])
}

/** The paths robots.txt closes. */
function disallowed(): string[] {
  const block = /disallow: \[([\s\S]*?)\]/.exec(codeOnly(read(ROBOTS)))
  assert.ok(block, 'robots should declare a disallow list')
  return literalsIn(block[1])
}

describe('the sitemap exists and is absolute', () => {
  test('both routes are present', () => {
    assert.doesNotThrow(() => read(SITEMAP))
    assert.doesNotThrow(() => read(ROBOTS))
  })

  test('it uses the one canonical origin the rest of the site uses', () => {
    // Not a second copy of the domain. ``SITE_ORIGIN`` already backs
    // ``metadataBase`` and every canonical on the site.
    for (const file of [SITEMAP, ROBOTS]) {
      const src = read(file)
      assert.match(src, /import \{ SITE_ORIGIN \} from '@\/lib\/collectiveSeo'/)
      assert.ok(
        !/https:\/\/freshcollective/.test(withoutDocComments(src)),
        `${file} should not spell the domain out again`,
      )
    }
    assert.match(
      read('src/lib/collectiveSeo.ts'),
      /SITE_ORIGIN = 'https:\/\/freshcollective\.au'/,
    )
  })

  test('every URL is absolute', () => {
    const src = withoutDocComments(read(SITEMAP))
    for (const m of src.matchAll(/url: ([^,\n]+)/g)) {
      assert.match(
        m[1],
        /SITE_ORIGIN/,
        'a sitemap URL must be absolute, not a bare path',
      )
    }
  })

  test('no URL carries a query string', () => {
    for (const path of publicPages()) {
      assert.ok(!path.includes('?'), `${path} carries a query string`)
    }
  })
})

describe('which pages are offered', () => {
  test('the pages the brief named are all there', () => {
    const pages = publicPages()
    for (const expected of ['/', '/about', '/for-creators', '/discover-places']) {
      assert.ok(pages.includes(expected), `${expected} should be offered`)
    }
  })

  test('no page that declares noindex is offered', () => {
    // The conflict worth catching: two files disagreeing about
    // whether a page may be indexed.
    const pages = publicPages()
    for (const route of ['creator-onboarding', 'messages']) {
      const src = read(`src/app/${route}/page.tsx`)
      assert.match(
        src,
        /robots: \{ index: false/,
        `${route} is expected to declare noindex`,
      )
      assert.ok(
        !pages.includes(`/${route}`),
        `/${route} declares noindex and must not be in the sitemap`,
      )
    }
  })

  test('a page that declares it is indexable may be offered', () => {
    assert.match(
      read('src/app/ecosystem-interest/page.tsx'),
      /robots: \{ index: true/,
    )
    assert.ok(publicPages().includes('/ecosystem-interest'))
  })

  test('no signed-in or internal surface is offered', () => {
    const pages = publicPages()
    for (const closed of [
      '/dashboard', '/settings', '/profile', '/notifications', '/messages',
      '/admin', '/creator-studio', '/creator', '/checkout', '/invites',
      '/onboarding', '/api', '/dev',
    ]) {
      assert.ok(
        !pages.some((p) => p === closed || p.startsWith(`${closed}/`)),
        `${closed} must not be in the sitemap`,
      )
    }
  })

  test('no authentication route is offered as a destination', () => {
    const pages = publicPages()
    for (const auth of [
      '/login', '/signup', '/verify-email', '/forgot-password',
      '/reset-password',
    ]) {
      assert.ok(!pages.includes(auth), `${auth} is not a destination`)
    }
  })

  test('a redirect is not offered', () => {
    // /build-your-place only redirects. Offering it would advertise
    // a URL that answers with a 307 to another one.
    assert.match(read('src/app/build-your-place/page.tsx'), /redirect\(/)
    assert.ok(!publicPages().includes('/build-your-place'))
  })

  test('there are no duplicates in the static list', () => {
    const pages = publicPages()
    assert.equal(new Set(pages).size, pages.length)
  })

  test('duplicates are filtered out of the finished list too', () => {
    assert.match(read(SITEMAP), /const seen = new Set<string>\(\)/)
  })
})

describe('how Collective URLs are obtained', () => {
  test('they come from the shared public query, not a written list', () => {
    const src = read(SITEMAP)
    assert.match(src, /\/api\/public\/sitemap\/collectives/)
    // No slug is ever spelled out here.
    assert.ok(
      !/'\/spaces\/[a-z]/.test(withoutDocComments(src)),
      'a Collective slug must never be hard-coded in the sitemap',
    )
  })

  test('each Collective is listed at its own canonical path', () => {
    // ``/spaces/{slug}`` redirects a non-member to the About page, so
    // listing it would advertise a duplicate of the canonical.
    assert.match(read(SITEMAP), /\/spaces\/\$\{encodeURIComponent\(c\.slug\)\}\/about/)
    assert.match(
      read('src/lib/collectiveSeo.ts'),
      /const canonical = `\/spaces\/\$\{slug\}\/about`/,
    )
  })

  test('lastModified comes from a recorded change, never from now', () => {
    const src = read(SITEMAP)
    assert.match(src, /lastModified: new Date\(c\.updated_at\)/)
    assert.ok(
      !/lastModified: new Date\(\)/.test(src),
      'a sitemap must not claim every page changed on every request',
    )
  })

  test('the static pages carry no invented date at all', () => {
    const src = read(SITEMAP)
    const staticEntry = /PUBLIC_PAGES\.map\(\(path\) => \(\{([\s\S]*?)\}\)\),/.exec(
      src,
    )
    assert.ok(staticEntry, 'the static entries should be built by a map')
    assert.ok(
      !/lastModified/.test(staticEntry[1]),
      'there is no reliable timestamp for a static page, so none is given',
    )
  })

  test('it degrades to the static pages if the API is unavailable', () => {
    // A sitemap that 500s is one a crawler may stop fetching; a
    // sitemap briefly missing its Collectives is one that finds them
    // a little later. Neither may publish anything private.
    const src = read(SITEMAP)
    assert.match(src, /catch \{\s*return \[\]/)
    assert.match(src, /if \(!res\.ok\) return \[\]/)
    assert.match(src, /if \(!Array\.isArray\(rows\)\) return \[\]/)
  })

  test('it revalidates rather than querying on every request', () => {
    const src = read(SITEMAP)
    const m = /export const revalidate = (\d+)/.exec(src)
    assert.ok(m, 'a revalidation window should be declared')
    assert.ok(Number(m[1]) >= 60, 'revalidating per-second defeats the point')
  })
})

describe('robots.txt', () => {
  test('it names the sitemap absolutely', () => {
    assert.match(read(ROBOTS), /sitemap: `\$\{SITE_ORIGIN\}\/sitemap\.xml`/)
  })

  test('it closes the private and administrative areas', () => {
    const closed = disallowed()
    for (const path of [
      '/admin/', '/creator-studio/', '/dashboard/', '/settings/',
      '/profile/', '/messages/', '/notifications/', '/checkout/',
      '/invites/', '/api/',
    ]) {
      assert.ok(closed.includes(path), `${path} should be disallowed`)
    }
  })

  test('it closes the authentication routes', () => {
    const closed = disallowed()
    for (const path of [
      '/login', '/signup', '/verify-email', '/forgot-password',
      '/reset-password',
    ]) {
      assert.ok(closed.includes(path), `${path} should be disallowed`)
    }
  })

  test('it does not close the public Collective pages', () => {
    // The hazard worth a test of its own: one over-broad prefix here
    // would delist every page the sitemap exists to advertise.
    for (const rule of disallowed()) {
      assert.ok(
        !'/spaces/'.startsWith(rule) && !rule.startsWith('/spaces'),
        `the rule ${rule} would block public Collective About pages`,
      )
    }
  })

  test('it does not close any page the sitemap offers', () => {
    // The two files must not contradict each other.
    const closed = disallowed()
    for (const page of publicPages()) {
      for (const rule of closed) {
        const blocks =
          rule === '/' ? true : page === rule || page.startsWith(rule)
        assert.ok(
          !blocks,
          `robots disallows ${rule}, which blocks the sitemap entry ${page}`,
        )
      }
    }
  })

  test('it allows the site by default', () => {
    assert.match(read(ROBOTS), /allow: '\/'/)
  })

  test('it says plainly that it is not access control', () => {
    // The dangerous misreading. Stated in the file so the next person
    // to widen it knows what it is and is not doing.
    assert.match(read(ROBOTS), /not access control/i)
  })
})
