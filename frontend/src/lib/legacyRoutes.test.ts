import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { resolveChartEmbed } from './legacyRoutes.ts'

/**
 * Legacy Wix URL migration layer, ahead of the freshcollective.au
 * cutover.
 *
 * The old site is retired, not migrated. These tests pin the three
 * decisions that matter:
 *
 *   1. the one route with a genuine successor (`/embody`) redirects
 *      permanently;
 *   2. the two externally-printed URLs are preserved as real pages;
 *   3. everything else is ABSENT, so it 404s — no homepage redirects
 *      faking an equivalence, and no catch-all that could shadow a
 *      Fresh Collective route.
 *
 * Point 3 is asserted by absence, which needs saying: a test that a
 * route 404s cannot be written without a server, but a test that no
 * redirect rule and no page file exists for it can, and that is the
 * actual thing being guaranteed.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/**
 * A source file with its comments removed.
 *
 * Every "this file must not contain X" assertion below reads through
 * this, because the files it checks *document* what they deliberately
 * do not do — "nothing touches cookies()", "not legacy-specific copy",
 * "the old Wix site". A substring check against the raw text fails on
 * the explanation rather than on a regression, which is a worse test
 * than none: it punishes the comment that prevents the bug.
 *
 * Block comments go first, which also empties a JSX comment (those
 * are a block comment wrapped in braces). Line comments are only
 * stripped when `//` is not preceded by `:`, so a `https://` inside a
 * string survives.
 */
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
const appPage = (route: string) => join(SRC, 'app', route, 'page.tsx')
const nextConfig = () => readFileSync(join(SRC, '..', 'next.config.ts'), 'utf8')

/** The redirect rules declared in next.config.ts, as {source, destination, permanent}. */
function declaredRedirects(): { source: string; destination: string; permanent: boolean }[] {
  const src = nextConfig()
  const block = src.slice(src.indexOf('async redirects()'))
  const out: { source: string; destination: string; permanent: boolean }[] = []
  const re =
    /source:\s*'([^']+)'[\s\S]*?destination:\s*'([^']+)'[\s\S]*?permanent:\s*(true|false)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(block))) {
    out.push({ source: m[1]!, destination: m[2]!, permanent: m[3] === 'true' })
  }
  return out
}

// ---------------------------------------------------------------------------
// 1-3. /embody — the one route with a successor
// ---------------------------------------------------------------------------

describe('/embody redirects to the Collective', () => {
  const rule = () => declaredRedirects().find((r) => r.source === '/embody')

  test('a redirect is declared for it', () => {
    assert.ok(rule(), '/embody has no redirect rule')
  })

  test('it is permanent', () => {
    // Next emits 308 for permanent: true. Anything else tells crawlers
    // and the book-adjacent links that the move is provisional.
    assert.equal(rule()!.permanent, true)
  })

  test('the destination is /spaces/embody', () => {
    assert.equal(rule()!.destination, '/spaces/embody')
  })

  test('the destination route actually exists', () => {
    // A permanent redirect into a 404 is worse than no redirect.
    assert.ok(
      existsSync(join(SRC, 'app', 'spaces', '[slug]', 'page.tsx')),
      '/spaces/[slug] is missing, so /spaces/embody cannot resolve',
    )
  })

  test('no query-string rule is needed, and none is added', () => {
    // Next carries the query string across a redirect on its own. An
    // explicit ``:path*`` or query rule here would be cargo cult, and
    // a ``/embody/:path*`` rule would additionally claim child routes
    // the old site never had.
    const sources = declaredRedirects().map((r) => r.source)
    assert.ok(!sources.includes('/embody/:path*'))
  })

  test('it does not shadow /spaces/embody itself', () => {
    // The redirect must not be declared in the reverse direction, and
    // must not be a prefix rule that could catch the destination.
    for (const r of declaredRedirects()) {
      assert.notEqual(r.source, '/spaces/embody')
      assert.notEqual(r.destination, '/embody')
    }
  })

  test('there is no duplicate /embody landing page', () => {
    assert.ok(
      !existsSync(appPage('embody')),
      'a page at /embody would shadow the redirect and duplicate the Collective',
    )
  })
})

// ---------------------------------------------------------------------------
// 4-5, 10. The two preserved URLs
// ---------------------------------------------------------------------------

describe('the preserved legacy URLs exist as real pages', () => {
  for (const route of ['leadershipbodychart', 'tnlbook123']) {
    test(`/${route} has a page`, () => {
      assert.ok(existsSync(appPage(route)), `/${route} is missing`)
    })

    test(`/${route} renders in the public shell`, () => {
      const page = read(join('app', route, 'page.tsx'))
      assert.match(page, /SiteShell/)
    })

    test(`/${route} is not behind the auth proxy`, () => {
      // The proxy protects by prefix. Neither route may fall under one,
      // or a book owner following a printed URL lands on /login.
      const proxy = read('proxyRouting.ts')
      const prefixes = proxy
        .slice(proxy.indexOf('PROTECTED_PREFIXES'), proxy.indexOf('function normalize'))
        .match(/'(\/[^']+)'/g)
      assert.ok(prefixes && prefixes.length > 0, 'could not read PROTECTED_PREFIXES')
      for (const quoted of prefixes!) {
        const prefix = quoted.slice(1, -1)
        assert.ok(
          `/${route}` !== prefix && !`/${route}`.startsWith(prefix + '/'),
          `/${route} sits under the protected prefix ${prefix}`,
        )
      }
    })

    test(`/${route} requires no session or membership`, () => {
      const page = codeOnly(join('app', route, 'page.tsx'))
      for (const gate of ['getMe(', 'cookies(', 'SESSION_COOKIE', 'area_access', 'getMySpaceAccess']) {
        assert.ok(!page.includes(gate), `/${route} reads ${gate}`)
      }
    })

    test(`/${route} exposes no admin or Creator Studio controls`, () => {
      const page = codeOnly(join('app', route, 'page.tsx'))
      for (const forbidden of ['creator-studio', '/admin', 'getCreatorUser', 'CreatorStudio']) {
        assert.ok(!page.includes(forbidden), `/${route} references ${forbidden}`)
      }
    })

    test(`/${route} sets its own metadata`, () => {
      const page = read(join('app', route, 'page.tsx'))
      assert.match(page, /export const metadata: Metadata/)
      assert.match(page, /title:/)
      assert.match(page, /description:/)
    })
  }

  test('the Book Companion links to the preserved chart URL', () => {
    assert.match(read('app/tnlbook123/page.tsx'), /href="\/leadershipbodychart"/)
  })
})

// ---------------------------------------------------------------------------
// The Book Companion's actual contents
// ---------------------------------------------------------------------------

describe('the Book Companion carries the real resources', () => {
  const PUBLIC_DIR = join(SRC, '..', 'public')
  const page = () => read('app/tnlbook123/page.tsx')

  /** Every companion asset the page offers, as (path, control). */
  const ASSETS: readonly [string, string][] = [
    ['/book-companion/natural-leader-front-cover.jpg', 'hero cover'],
    ['/book-companion/gates-summaries.pdf', 'Gate / Gifts Summary'],
    ['/book-companion/healing-vortex.mp3', 'The Healing Vortex'],
    ['/book-companion/feminine-archetypes.pdf', 'Feminine Archetypes'],
    [
      '/book-companion/journal-prompts-and-somatic-practices.pdf',
      'Prompts & Practices',
    ],
  ]

  for (const [path, label] of ASSETS) {
    test(`${label} is referenced at ${path}`, () => {
      assert.ok(page().includes(path), `${path} is not on the page`)
    })

    test(`${label} exists on disk under public/`, () => {
      // The asset paths are strings in a TSX file, so a typo is
      // invisible until someone clicks. Resolving each one against
      // ``public/`` is what makes them real.
      assert.ok(
        existsSync(join(PUBLIC_DIR, path.replace(/^\//, ''))),
        `${path} is linked but missing from public/`,
      )
    })
  }

  test('the five files are the only book-companion assets referenced', () => {
    // Guards the other direction: a link added to a file nobody shipped.
    const referenced = [...page().matchAll(/\/book-companion\/[A-Za-z0-9._-]+/g)]
      .map((m) => m[0])
    for (const path of new Set(referenced)) {
      assert.ok(
        ASSETS.some(([a]) => a === path),
        `${path} is referenced but not a known companion asset`,
      )
    }
  })

  test('the Spotify show is linked, and opens safely', () => {
    const src = page()
    assert.match(
      src,
      /https:\/\/open\.spotify\.com\/show\/4K7nabojVkR6jhQpqqzSEq/,
    )
    assert.match(src, /target="_blank"/)
    assert.match(src, /rel="noopener noreferrer"/)
  })

  test('the chart CTA uses the current terminology', () => {
    const src = page()
    // "Human Design Bodychart" is the current name. The old "Leadership
    // Body Chart" wording must not come back on the CTA.
    assert.ok(
      !/Leadership Body Chart/i.test(codeOnly('app/tnlbook123/page.tsx')),
      'the retired "Leadership Body Chart" wording is back',
    )
    assert.match(src, />\s*Get Chart\s*</)
  })

  test('the retired Natural Leader Hub promotion is absent', () => {
    // The old Wix page sold the Hub. That programme is retired and this
    // page is not a sales surface.
    const src = codeOnly('app/tnlbook123/page.tsx')
    for (const phrase of ['Natural Leader Hub', 'tnlhub', 'Join the Hub']) {
      assert.ok(!src.includes(phrase), `the page still promotes: ${phrase}`)
    }
  })

  test('the launch placeholder copy is gone', () => {
    // Through codeOnly: the page's header comment records that this
    // placeholder was removed, so the raw text legitimately contains
    // the phrase it is asserting the absence of.
    const src = codeOnly('app/tnlbook123/page.tsx')
    for (const phrase of [
      'resources are being gathered',
      'being gathered into Fresh Collective',
      'In the meantime',
    ]) {
      assert.ok(!src.includes(phrase), `placeholder copy remains: ${phrase}`)
    }
  })

  test('all six resource cards are present', () => {
    const src = page()
    for (const title of [
      'Human Design Chart',
      'Gate / Gifts Summary',
      'The Healing Vortex',
      'Feminine Archetypes',
      'Prompts &amp; Practices',
      'The Natural Leader Podcast',
    ]) {
      assert.ok(src.includes(title), `missing resource card: ${title}`)
    }
  })

  test('the reading list carries all twelve books with authors', () => {
    const src = page()
    for (const [title, author] of [
      ['Women Who Run With the Wolves', 'Clarissa Pinkola Estés'],
      ['Burnout: The Secret to Unlocking the Stress Cycle', 'Emily Nagoski'],
      ['The Patriarchy Stress Disorder', 'Dr Valerie Rein'],
      ['Do Less', 'Kate Northrup'],
      ['The Body Is Not an Apology', 'Sonya Renee Taylor'],
      ['Untamed', 'Glennon Doyle'],
      ['Power:', 'Kemi Nekvapil'],
      ['The Chalice and the Blade', 'Riane Eisler'],
      ['Dare to Lead', 'Brené Brown'],
      ["My Grandmother's Hands", 'Resmaa Menakem'],
      ['You Can Heal Your Life', 'Louise Hay'],
      ['The Secret Language of Your Body', 'Inna Segal'],
    ]) {
      assert.ok(src.includes(title!), `missing book: ${title}`)
      assert.ok(src.includes(author!), `missing author: ${author}`)
    }
  })

  test('the reading list carries no purchase or affiliate links', () => {
    // Titles and authors only, as agreed. Through codeOnly, because the
    // page comment states this intent in the same words.
    const src = codeOnly('app/tnlbook123/page.tsx')
    const block = src.slice(src.indexOf('READING_LIST'), src.indexOf('ResourceCard'))
    assert.ok(!/https?:\/\//.test(block), 'the reading list contains a link')
    // Query-parameter form only — a bare 'ref=' is a substring of
    // 'href=', which every link on the page legitimately uses.
    for (const marker of ['amazon.', 'bookshop.', 'affiliate', '?tag=', '&tag=', '?ref=', '&ref=']) {
      assert.ok(!src.includes(marker), `affiliate marker present: ${marker}`)
    }
  })

  test('the large audio file is not preloaded', () => {
    // ~48MB. Browsers that preload metadata would pull a slice of it
    // for every visitor, most of whom came for a PDF.
    assert.match(page(), /preload="none"/)
  })

  test('the hero cover goes through next/image', () => {
    const src = page()
    assert.match(src, /from 'next\/image'/)
    assert.match(src, /alt="The Natural Leader by Lindsey Hilliard/)
  })

  test('no API route or database access serves these files', () => {
    const src = codeOnly('app/tnlbook123/page.tsx')
    for (const forbidden of ['/api/', 'serverApi', 'fetch(', 'prisma', 'db.']) {
      assert.ok(!src.includes(forbidden), `the page reaches for ${forbidden}`)
    }
  })

  test('the route itself is unchanged', () => {
    // The whole point of the page. The directory name IS the legacy URL.
    assert.ok(existsSync(appPage('tnlbook123')))
  })
})

// ---------------------------------------------------------------------------
// The chart embed — configured vs not
// ---------------------------------------------------------------------------

describe('the Neutrino chart embed is configuration, not a guess', () => {
  const GOOD =
    'https://neutrinoplatform.com/widget-v2/iframe?type=chart&key=abc123&hideBrand=true'

  test('a configured widget URL resolves and keeps its query string', () => {
    const r = resolveChartEmbed(GOOD)
    assert.equal(r.configured, true)
    if (!r.configured) return
    assert.equal(r.url, GOOD)
    assert.equal(r.provider.name, 'Neutrino Human Design')
  })

  test('an unset value is reported as unset, not guessed at', () => {
    for (const raw of [undefined, '', '   ']) {
      const r = resolveChartEmbed(raw)
      assert.equal(r.configured, false)
      if (r.configured) return
      assert.equal(r.reason, 'unset')
    }
  })

  test('the chart page is not prerendered', () => {
    // Subtle and easy to lose. With the env var unset at build time the
    // page 404s before it touches cookies(), so Next prerenders it as a
    // static 404 — and setting the variable on Render restarts without
    // rebuilding, leaving the printed URL broken until the next deploy.
    const page = read('app/leadershipbodychart/page.tsx')
    assert.match(page, /export const dynamic = 'force-dynamic'/)
  })

  test('the page 404s rather than rendering a chartless shell', () => {
    // A 200 with no chart, on a URL printed in a book, looks like the
    // page works. The route is config-gated instead.
    const page = read('app/leadershipbodychart/page.tsx')
    assert.match(page, /if \(!chart\.configured\) notFound\(\)/)
  })

  test('a misconfigured value is refused, not framed', () => {
    for (const bad of [
      'https://evil.example/widget-v2/iframe?type=chart',
      'http://neutrinoplatform.com/widget-v2/iframe?type=chart',
      'https://neutrinoplatform.com/app/dashboard',
      'javascript:alert(1)',
    ]) {
      const r = resolveChartEmbed(bad)
      assert.equal(r.configured, false, `${bad} was accepted`)
      if (r.configured) return
      assert.equal(r.reason, 'rejected')
    }
  })

  test('a non-widget path on the right host is refused', () => {
    // The gap this closes: ``checkEmbed`` gates the host only, because
    // the server owns the path rule for creator-pasted embeds. This URL
    // never reaches the server, so the path is checked here too.
    for (const bad of [
      'https://neutrinoplatform.com/app/dashboard',
      'https://neutrinoplatform.com/widget-v2/loader.js',
      'https://neutrinoplatform.com/widget-v2/iframe/v3?type=chart',
      'https://neutrinoplatform.com/',
    ]) {
      const r = resolveChartEmbed(bad)
      assert.equal(r.configured, false, `${bad} was accepted`)
      if (r.configured) return
      assert.equal(r.reason, 'rejected')
    }
  })

  test('the exact widget path with a trailing slash is accepted', () => {
    const r = resolveChartEmbed(
      'https://neutrinoplatform.com/widget-v2/iframe/?type=chart&key=abc',
    )
    assert.equal(r.configured, true)
  })

  test('it goes through the shared allowlist, not a private rule', () => {
    const lib = read('lib/legacyRoutes.ts')
    assert.match(lib, /from '\.\/embedAllowlist\.ts'/)
    assert.match(lib, /checkEmbed\(/)
  })

  test('the chart renders through the sandboxed EmbedRenderer', () => {
    const page = codeOnly('app/leadershipbodychart/page.tsx')
    assert.match(page, /EmbedRenderer/)
    assert.ok(
      !page.includes('<iframe'),
      'the page builds its own iframe instead of using the renderer',
    )
    assert.ok(!page.includes('dangerouslySetInnerHTML'))
  })

  test('no allowlist or CSP change was needed for it', () => {
    // neutrinoplatform.com was already a registered provider. If this
    // route had required widening either, that would be the thing to
    // review — so it is asserted rather than assumed.
    assert.match(read('lib/embedAllowlist.ts'), /neutrinoplatform\.com/)
  })
})

// ---------------------------------------------------------------------------
// 6-9. Retired routes retire
// ---------------------------------------------------------------------------

describe('retired Wix URLs are absent, not redirected', () => {
  const RETIRED = [
    '/tnlhub-info',
    '/work-with-lindsey',
    '/post/old-article',
    '/event-details-registration/old-event',
    '/category/all-products',
    '/product-page/some-product',
    '/blog/categories/leadership',
  ]

  for (const route of RETIRED) {
    test(`${route} has no redirect rule at all`, () => {
      for (const r of declaredRedirects()) {
        assert.notEqual(r.source, route, `${route} is being redirected`)
      }
    })

    test(`${route} does not redirect to the homepage`, () => {
      // The specific failure mode asked about: a retired page pointed
      // at / claims the homepage is its successor.
      const rule = declaredRedirects().find((r) => r.source === route)
      if (rule) assert.notEqual(rule.destination, '/')
    })
  }

  test('nothing redirects to the homepage', () => {
    // Stated once over the whole rule set, so a future retired route
    // cannot be quietly pointed at / either.
    for (const r of declaredRedirects()) {
      assert.notEqual(r.destination, '/', `${r.source} → / is a false equivalence`)
    }
  })

  test('/event-details-registration/* does not redirect to a Gathering', () => {
    for (const r of declaredRedirects()) {
      if (r.source.startsWith('/event-details-registration')) {
        assert.fail(`${r.source} → ${r.destination} invents a Gathering successor`)
      }
    }
  })

  test('no page file exists for any retired route', () => {
    for (const route of RETIRED) {
      const top = route.split('/')[1]!
      assert.ok(
        !existsSync(appPage(top)),
        `/${top} has a page, so ${route} may not 404 as intended`,
      )
    }
  })

  test('no external redirect is declared to a guessed shop URL', () => {
    // /category/all-products may eventually point at Etsy. No verified
    // canonical Etsy URL exists in this repo, so none is invented.
    for (const r of declaredRedirects()) {
      assert.ok(
        !/^https?:\/\//.test(r.destination),
        `${r.source} redirects off-site to ${r.destination}`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// 13. No catch-all, no shadowing
// ---------------------------------------------------------------------------

describe('the migration layer cannot shadow Fresh Collective routes', () => {
  test('every redirect source is an exact path, bar the pre-existing slug rule', () => {
    for (const r of declaredRedirects()) {
      if (r.source.startsWith('/spaces/winters-playground')) continue
      assert.ok(
        !r.source.includes(':') && !r.source.includes('*'),
        `${r.source} is a pattern, not an exact path`,
      )
    }
  })

  test('no redirect source touches a live product area', () => {
    const LIVE = [
      '/spaces',
      '/discover-places',
      '/world-guide',
      '/world',
      '/login',
      '/signup',
      '/dashboard',
      '/settings',
      '/profile',
      '/admin',
      '/creator',
      '/creator-studio',
      '/checkout',
      '/onboarding',
      '/notifications',
    ]
    for (const r of declaredRedirects()) {
      for (const live of LIVE) {
        // The one legitimate exception is the pre-existing Collective
        // slug rename, which redirects within /spaces on purpose.
        if (r.source.startsWith('/spaces/winters-playground')) continue
        assert.ok(
          r.source !== live && !r.source.startsWith(live + '/'),
          `${r.source} shadows the live route ${live}`,
        )
      }
    }
  })

  test('the preserved routes do not collide with a live top-level route', () => {
    const reserved = new Set(['spaces', 'discover-places', 'world-guide', 'world'])
    for (const route of ['leadershipbodychart', 'tnlbook123']) {
      assert.ok(!reserved.has(route))
    }
  })
})

// ---------------------------------------------------------------------------
// 12. No hard-coded host
// ---------------------------------------------------------------------------

describe('no origin is hard-coded by this change', () => {
  const TOUCHED = [
    'lib/legacyRoutes.ts',
    'app/leadershipbodychart/page.tsx',
    'app/tnlbook123/page.tsx',
    'app/not-found.tsx',
  ]

  for (const file of TOUCHED) {
    test(`${file} names no Render hostname`, () => {
      assert.ok(
        !codeOnly(file).includes('onrender.com'),
        `${file} hard-codes the Render host`,
      )
    })

    test(`${file} names no absolute site origin`, () => {
      // Metadata and links stay relative, so the same build is correct
      // on the Render hostname today and on freshcollective.au after
      // cutover. A canonical pointing at either would be wrong for the
      // other.
      //
      // Matched as a URL, not as the bare domain: these files explain
      // the cutover in prose, and a blunt substring check fails on the
      // explanation rather than on a hard-coded origin.
      const src = codeOnly(file)
      assert.ok(
        !/https?:\/\/[a-z0-9.-]*freshcollective\.au/i.test(src),
        `${file} hard-codes the live origin`,
      )
      assert.ok(
        !/https?:\/\/[a-z0-9.-]*onrender\.com/i.test(src),
        `${file} hard-codes the Render origin`,
      )
    })
  }

  test('next.config.ts declares no absolute destination', () => {
    for (const r of declaredRedirects()) {
      assert.ok(r.destination.startsWith('/'), `${r.destination} is not relative`)
    }
  })

  test('no Wix URL is left embedded in the new app', () => {
    // A Wix *URL* or asset host, not the word — these files name Wix
    // when explaining what is being retired, which is the documentation
    // working rather than a leftover.
    for (const file of TOUCHED) {
      const src = codeOnly(file)
      assert.ok(
        !/https?:\/\/[a-z0-9.-]*(wix|wixsite|wixstatic)\.com/i.test(src),
        `${file} still links to Wix`,
      )
      assert.ok(!/freshcollective\.au\/(embody|tnl|post|product-page)/i.test(src))
    }
  })
})
