/**
 * Which pages may be reported to an analytics service.
 *
 * This is the privacy boundary, so it is tested for what it lets
 * through as well as what it stops — a file that only proved "nothing
 * is tracked" would pass against a predicate that always returned
 * false, and that failure mode is invisible (missing numbers, never
 * an error). That property matters more than usual now: Cloudflare
 * Web Analytics was removed, nothing consumes ``isTrackablePath``,
 * and a rule with no caller is exactly the kind of thing that rots
 * quietly. These tests are what keep it honest until a replacement
 * arrives — including the source-reading ones below, which re-check
 * every allow-listed page against the app as it actually is today.
 *
 * The cases that matter most are the URLs carrying a bearer
 * credential. ``/invites/{token}``, ``/reset-password?token=`` and
 * ``/verify-email?token=`` would each put a live secret into a
 * dashboard, since Path is a reportable dimension everywhere.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import { existsSync, readFileSync } from 'node:fs'

import { isTrackablePath, __lists } from './analytics.ts'

// ---------------------------------------------------------------------------
// 1 · What is tracked — the control for everything below
// ---------------------------------------------------------------------------

describe('public pages are tracked', () => {
  for (const path of [
    '/',
    '/about',
    '/for-creators',
    '/real-journey',
    '/membership',
    '/ecosystem-interest',
    '/tnlbook',
    '/guides',
    '/starter-kit',
    '/spaces',
    '/discover-places',
    '/world-guide',
  ]) {
    test(`${path} is tracked`, () => {
      assert.equal(isTrackablePath(path), true)
    })
  }

  test('a Location page is tracked', () => {
    assert.equal(isTrackablePath('/discover-places/misty-harbour'), true)
  })

  test('a World Guide document is tracked', () => {
    assert.equal(isTrackablePath('/world-guide/finding-your-collective'), true)
  })

  test("a Collective's public About page is tracked", () => {
    assert.equal(isTrackablePath('/spaces/moonlit-circle/about'), true)
  })

  test("a Pathway's public About page is tracked", () => {
    assert.equal(
      isTrackablePath('/spaces/moonlit-circle/pathways/slowing-down/about'),
      true,
    )
  })
})

// ---------------------------------------------------------------------------
// 1b · Unlisted pages: public, reachable, and still not counted
// ---------------------------------------------------------------------------

describe('an unlisted page is not tracked', () => {
  // ``/tnlbook123`` is the Book Companion. It is public, it needs no
  // account, and it must keep resolving for anyone who types the URL
  // printed in the book — but it declares ``robots: noindex`` and is
  // absent from the sitemap, so the site does not advertise it. A page
  // the site does not advertise is not a page it counts: the same
  // answer, given consistently to a crawler and to analytics.
  //
  // Nothing on it is sensitive, which is why this is a decision rather
  // than a safety rule. It is tested because the three files have to
  // agree, and the way they stop agreeing is one of them being edited
  // on its own.

  test('/tnlbook123 is not tracked', () => {
    assert.equal(isTrackablePath('/tnlbook123'), false)
    assert.equal(isTrackablePath('/tnlbook123/'), false)
    assert.equal(isTrackablePath('/tnlbook123?utm_source=book'), false)
  })

  test('it is absent from the allow-list, not refused', () => {
    // Deliberately NOT in ``NEVER_TRACKED``: that list is for paths
    // that must never be reported whatever the allow-list says —
    // tokens, member areas, admin. This page is simply unlisted, and
    // the fail-closed allow-list is what excludes it. Putting it in
    // the refusal list would overstate the reason.
    assert.ok(!__lists.TRACKED_EXACT.has('/tnlbook123'))
    assert.ok(!__lists.NEVER_TRACKED.includes('/tnlbook123'))
  })

  test('/tnlbook, the opt-in page, is still tracked', () => {
    // The control. The two are different steps of one flow and only
    // one of them came off the list — without this, removing both
    // would pass.
    assert.equal(isTrackablePath('/tnlbook'), true)
  })

  test('the page itself declares noindex, which is why it is unlisted', () => {
    // Read from source, in the manner of section 8 below: the reason
    // this page is absent lives in another file, and a test that only
    // asserted the absence would pass just as happily if that reason
    // were deleted.
    const src = readFileSync('src/app/tnlbook123/page.tsx', 'utf8')
    assert.match(src, /robots: \{ index: false, follow: false \}/)
  })
})

// ---------------------------------------------------------------------------
// 1c · Guides
// ---------------------------------------------------------------------------

describe('Guides are tracked; the admin behind them is not', () => {
  // Public articles with no account, no gate and no visitor-specific
  // content — the standard this allow-list applies. The pairing that
  // matters is the last two tests: the same Guide has a public URL
  // that is counted and an admin preview URL that must never be.

  test('the index is tracked', () => {
    assert.equal(isTrackablePath('/guides'), true)
    assert.equal(isTrackablePath('/guides/'), true)
  })

  test('one Guide is tracked', () => {
    assert.equal(isTrackablePath('/guides/moving-your-community'), true)
    assert.equal(isTrackablePath('/guides/moving-your-community?from=home'), true)
  })

  test('the pattern cannot widen by a deeper path', () => {
    assert.equal(isTrackablePath('/guides/a/b'), false)
    assert.equal(isTrackablePath('/guides/a/b/c'), false)
  })

  test('the admin surface is not tracked', () => {
    for (const p of [
      '/admin/guides',
      '/admin/guides/new',
      '/admin/guides/gde_123',
    ]) {
      assert.equal(isTrackablePath(p), false, p)
    }
  })

  test('the admin preview of a Guide is not tracked', () => {
    // The one worth naming. The preview renders the real public
    // article layout, so it is the surface most likely to be mistaken
    // for the public page — and it is reachable only by an
    // administrator, whose visits must not be counted as readership.
    assert.equal(isTrackablePath('/admin/guides/gde_123/preview'), false)
  })

  test('a draft has no trackable path of its own', () => {
    // Nothing to assert about a draft URL, because there is not one:
    // /guides/{slug} 404s until the Guide is published. Pinned as the
    // reasoning so the next reader does not go looking for a rule
    // that would have to exist if drafts were reachable.
    assert.equal(isTrackablePath('/guides/an-unpublished-draft'), true)
  })
})

// ---------------------------------------------------------------------------
// 2 · Bearer credentials in URLs — the cases with no recovery
// ---------------------------------------------------------------------------

describe('URLs carrying a secret are never tracked', () => {
  test('an invitation token in the path', () => {
    assert.equal(isTrackablePath('/invites/8f3c1d9e4b7a2056'), false)
    assert.equal(isTrackablePath('/invites'), false)
  })

  test('a password reset token in the query', () => {
    assert.equal(
      isTrackablePath('/reset-password?token=' + 'a'.repeat(64)),
      false,
    )
  })

  test('an email verification token in the query', () => {
    assert.equal(
      isTrackablePath('/verify-email?token=' + 'b'.repeat(64)),
      false,
    )
  })

  test('the auth pages are left out, ?next= and all', () => {
    assert.equal(isTrackablePath('/login?next=%2Fdashboard'), false)
    assert.equal(isTrackablePath('/signup'), false)
    assert.equal(isTrackablePath('/forgot-password'), false)
  })
})

// ---------------------------------------------------------------------------
// 3 · Authenticated and internal surfaces
// ---------------------------------------------------------------------------

describe('member and internal areas are never tracked', () => {
  for (const path of [
    '/dashboard',
    '/profile/usr_123',
    '/settings',
    '/onboarding',
    '/messages/thr_456',
    '/notifications',
    '/checkout',
    '/admin',
    '/admin/collectives/moonlit-circle',
    '/creator-studio',
    '/creator-studio/pathways/slowing-down',
    '/creator/spaces/moonlit-circle',
    '/creator-onboarding',
    '/dev/onboarding-preview',
  ]) {
    test(`${path} is not tracked`, () => {
      assert.equal(isTrackablePath(path), false)
    })
  }

  test('a private conversation is not tracked', () => {
    assert.equal(isTrackablePath('/spaces/moonlit-circle/community'), false)
    assert.equal(
      isTrackablePath('/spaces/moonlit-circle/community/cp_789'),
      false,
    )
  })

  test('a member profile inside a Collective is not tracked', () => {
    assert.equal(
      isTrackablePath('/spaces/moonlit-circle/members/mem_1'),
      false,
    )
  })
})

// ---------------------------------------------------------------------------
// 4 · Area-gated Collective pages stay out
// ---------------------------------------------------------------------------

describe('pages whose audience depends on the Collective stay out', () => {
  // ``/spaces/x/events`` is public in a Collective that publishes its
  // Gatherings and members-only in the next one. Tracking it would
  // mean tracking a members-only page whenever a member opened it, so
  // only the public-by-design About surfaces are allowed.
  for (const path of [
    '/spaces/moonlit-circle',
    '/spaces/moonlit-circle/events',
    '/spaces/moonlit-circle/events/evt_1',
    '/spaces/moonlit-circle/pathways',
    '/spaces/moonlit-circle/pathways/slowing-down',
    '/spaces/moonlit-circle/gathering-series/term-4',
    '/spaces/moonlit-circle/messages',
  ]) {
    test(`${path} is not tracked`, () => {
      assert.equal(isTrackablePath(path), false)
    })
  }
})

// ---------------------------------------------------------------------------
// 5 · The matching itself cannot be widened by accident
// ---------------------------------------------------------------------------

describe('path matching', () => {
  test('a pattern cannot be widened by a deeper path', () => {
    assert.equal(isTrackablePath('/spaces/x/about'), true)
    assert.equal(isTrackablePath('/spaces/x/about/secret'), false)
    assert.equal(isTrackablePath('/world-guide/a/b'), false)
  })

  test('query strings and fragments are stripped before matching', () => {
    assert.equal(isTrackablePath('/for-creators?utm_source=news'), true)
    assert.equal(isTrackablePath('/for-creators#why'), true)
    // ...but stripping must not rescue a refused path.
    assert.equal(isTrackablePath('/invites/abc?x=1'), false)
    assert.equal(isTrackablePath('/build-your-collective?mode=x'), false)
  })

  test('a trailing slash is the same page', () => {
    assert.equal(isTrackablePath('/for-creators/'), true)
    assert.equal(isTrackablePath('/'), true)
  })

  test('refusal is matched on segment boundaries, not substrings', () => {
    // ``/creator-onboarding`` is not a child of ``/creator`` — both are
    // refused, but for their own reasons, and a substring check here
    // would have hidden a bug in the prefix logic.
    assert.equal(isTrackablePath('/creator-onboarding'), false)
    assert.equal(isTrackablePath('/creator'), false)
  })

  test('an unknown page is not tracked', () => {
    // Fails closed: the next route someone adds is invisible to
    // analytics until it is named, which is a missing number rather
    // than a leaked secret.
    assert.equal(isTrackablePath('/some-new-page'), false)
    // Substring-vs-exact: ``/membership`` is tracked, ``/memberships``
    // is not.
    assert.equal(isTrackablePath('/memberships'), false)
  })

  test('a non-path input is refused rather than guessed at', () => {
    assert.equal(isTrackablePath(''), false)
    assert.equal(isTrackablePath('https://evil.test/about'), false)
  })
})

// ---------------------------------------------------------------------------
// 6 · The two lists cannot contradict each other
// ---------------------------------------------------------------------------

describe('the allow-list and the refusal list are disjoint', () => {
  test('no exact entry sits under a refused root', () => {
    for (const path of __lists.TRACKED_EXACT) {
      for (const prefix of __lists.NEVER_TRACKED) {
        assert.ok(
          !(path === prefix || path.startsWith(prefix + '/')),
          `${path} is allowed and refused at once`,
        )
      }
    }
  })

  test('no pattern can match a refused root', () => {
    // Sampled against a realistic path under each refused root, so a
    // future pattern written with ``.*`` would be caught here rather
    // than in production.
    for (const prefix of __lists.NEVER_TRACKED) {
      for (const candidate of [prefix, `${prefix}/abc`, `${prefix}/abc/def`]) {
        for (const re of __lists.TRACKED_PATTERNS) {
          assert.ok(
            !re.test(candidate),
            `${re} matches the refused path ${candidate}`,
          )
        }
      }
    }
  })
})


// ---------------------------------------------------------------------------
// 7 · Pages that only look public
// ---------------------------------------------------------------------------

describe('a page must render for an anonymous visitor, not merely be unprotected', () => {
  // The regression. Three pages shipped on the allow-list because
  // "public" was derived from the middleware's protected prefixes and
  // the route listing — but a page can gate or redirect itself without
  // the middleware knowing, and all three did. Production answered
  // each with a 307 the first time anyone asked it.
  //
  // Two of them are still refused below. The third, ``/about``, has
  // since been built into a real page and is tracked again — see the
  // section that follows, and note that the property tested here is
  // unchanged: it is on the list *because* it renders, not because it
  // is unprotected.

  test('/build-your-place is not tracked — it is a legacy alias', () => {
    assert.equal(isTrackablePath('/build-your-place'), false)
  })

  test('/build-your-collective is not tracked — it is an authenticated surface', () => {
    // The one that mattered. Signed out it redirects to /login, so the
    // 307 looked like any other gated route; but a signed-in creator
    // renders it, and the beacon would have reported a page view on the
    // creator ritual. Its ?mode= and ?slug= parameters were never at
    // risk — the beacon strips query strings — but the path should
    // never have been counted.
    assert.equal(isTrackablePath('/build-your-collective'), false)
    assert.equal(isTrackablePath('/build-your-collective?mode=edit-identity&slug=embody'), false)
  })

  test('the two authenticated ones are refused, not merely unlisted', () => {
    // Defence in depth: absence from the allow-list already excludes
    // them, and naming them in the refusal list means a careless
    // re-addition still cannot reach them.
    for (const prefix of ['/build-your-collective', '/build-your-place']) {
      assert.ok(
        __lists.NEVER_TRACKED.includes(prefix),
        `${prefix} must be refused outright, not just left out`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// 7b · /about, which earned its place back
// ---------------------------------------------------------------------------

describe('/about is tracked, and for the right reason', () => {
  // It came off this list as a dead entry: the route existed but its
  // whole body was ``redirect('/')``, so no document ever rendered at
  // that pathname and the beacon could not have fired there. It is now
  // the "Why Fresh Collective exists" story page — a public reading
  // page with no guard, no redirect and the same content for every
  // visitor, which is the standard this allow-list actually applies.
  //
  // Tested as the property rather than the conclusion. "It is on the
  // list" is one assertion and worth little on its own; "the page it
  // names renders for an anonymous visitor" is the reason, and it is
  // what would change if someone turned the route back into a stub.

  test('/about is tracked', () => {
    assert.equal(isTrackablePath('/about'), true)
    assert.equal(isTrackablePath('/about/'), true)
    assert.equal(isTrackablePath('/about?utm_source=news'), true)
  })

  test('it is a real page, not a redirect to one', () => {
    const src = readFileSync('src/app/about/page.tsx', 'utf8')
    assert.ok(
      !/\bredirect\(/.test(src),
      '/about redirects again — it must come off the allow-list if so',
    )
    assert.match(src, /export default function AboutPage/)
  })

  test('nothing on it is gated or visitor-specific', () => {
    // The requirement is stricter than "an anonymous visitor is not
    // refused": the content has to be the same for everyone, or the
    // page view would be reporting a members-only render.
    const src = readFileSync('src/app/about/page.tsx', 'utf8')
    for (const guard of [
      /requireArea\(/,
      /requireAuthenticatedUser/,
      /getCurrentUser/,
      /cookies\(/,
      /notFound\(/,
    ]) {
      assert.ok(!guard.test(src), `/about matches ${guard}`)
    }
  })

  test('it is absent from the refusal list, as a tracked page must be', () => {
    assert.ok(__lists.TRACKED_EXACT.has('/about'))
    assert.ok(!__lists.NEVER_TRACKED.includes('/about'))
  })

  test('the sitemap offers it too, so the two files agree', () => {
    // ``/about`` has been in ``PUBLIC_PAGES`` throughout, including
    // while it was a redirect. Now that both files name it, a reader
    // finds one answer rather than two.
    const sitemap = readFileSync('src/app/sitemap.ts', 'utf8')
    assert.match(sitemap, /^\s*'\/about',$/m)
  })
})

// ---------------------------------------------------------------------------
// 8 · Every allow-listed page, checked against its own source
// ---------------------------------------------------------------------------

describe('no allow-listed page gates or redirects itself', () => {
  // The test that would have caught the three above. A page that calls
  // ``redirect()``, ``requireArea()`` or an auth guard is not a public
  // page, whatever the middleware thinks — so read each one and say so.
  //
  // Asserted from source rather than over HTTP: the suite has no
  // network, and the property worth pinning is in the code anyway.

  const PAGE_OF_PATTERN: ReadonlyArray<[string, string]> = [
    ['/discover-places/:slug', 'src/app/discover-places/[slug]/page.tsx'],
    ['/world-guide/:slug', 'src/app/world-guide/[slug]/page.tsx'],
    ['/spaces/:slug/about', 'src/app/spaces/[slug]/about/page.tsx'],
    [
      '/spaces/:slug/pathways/:slug/about',
      'src/app/spaces/[slug]/pathways/[pathway-slug]/about/page.tsx',
    ],
    ['/guides/:slug', 'src/app/guides/[slug]/page.tsx'],
  ]

  /** ``/`` → app/page.tsx; ``/x`` → app/x/page.tsx. */
  function pageFileFor(path: string): string {
    return path === '/' ? 'src/app/page.tsx' : `src/app/${path.slice(1)}/page.tsx`
  }

  function assertRenders(label: string, file: string) {
    const src = readFileSync(file, 'utf8')
    for (const banned of [/\bredirect\(/, /requireArea\(/, /requireAuthenticatedUser/]) {
      assert.ok(
        !banned.test(src),
        `${label} (${file}) matches ${banned} — it gates or redirects itself, `
          + 'so it is not a page an anonymous visitor renders and must not '
          + 'be on the analytics allow-list',
      )
    }
  }

  for (const path of __lists.TRACKED_EXACT) {
    test(`${path} renders rather than redirecting`, () => {
      const file = pageFileFor(path)
      assert.ok(existsSync(file), `${path} has no page at ${file}`)
      assertRenders(path, file)
    })
  }

  for (const [label, file] of PAGE_OF_PATTERN) {
    test(`${label} renders rather than redirecting`, () => {
      assert.ok(existsSync(file), `missing ${file}`)
      assertRenders(label, file)
    })
  }

  test('every pattern in the allow-list has a page checked above', () => {
    // Keeps the map honest: add a pattern without adding its page here
    // and this fails, rather than the pattern going unchecked.
    assert.equal(__lists.TRACKED_PATTERNS.length, PAGE_OF_PATTERN.length)
  })
})


// ---------------------------------------------------------------------------
// 9 · The private surfaces, named one by one
// ---------------------------------------------------------------------------

describe('no private surface can be reported, by any route into it', () => {
  // Written as the explicit list rather than by category, so the
  // answer to "is X excluded?" is greppable. Each entry is tested at
  // its root, one level deep, and with a query string, because a
  // client-side navigation can arrive at any of those shapes.

  const PRIVATE: ReadonlyArray<[string, string]> = [
    ['the member dashboard', '/dashboard'],
    ['platform administration', '/admin'],
    ['Creator Studio', '/creator-studio'],
    ['the legacy creator routes', '/creator'],
    ['the creator ritual', '/build-your-collective'],
    ['account settings', '/settings'],
    ['onboarding', '/onboarding'],
    ['the personal notification centre', '/notifications'],
    ['checkout', '/checkout'],
    ['private messages', '/messages'],
    ['member profiles', '/profile'],
  ]

  for (const [label, root] of PRIVATE) {
    test(`${label} (${root}) is excluded at every depth`, () => {
      for (const p of [root, `${root}/`, `${root}/abc`, `${root}/abc/def`, `${root}?x=1`]) {
        assert.equal(isTrackablePath(p), false, `${p} must not be tracked`)
      }
    })
  }

  test('private Collective areas are excluded, including identifiers', () => {
    // ``/spaces/{slug}`` is not proxy-protected — each area decides for
    // itself server-side — so these are excluded by the allow-list
    // naming only the two public About shapes, never by middleware.
    for (const p of [
      '/spaces/moonlit-circle',
      '/spaces/moonlit-circle/community',
      '/spaces/moonlit-circle/community/cp_abc123',
      '/spaces/moonlit-circle/messages',
      '/spaces/moonlit-circle/messages/thr_abc123',
      '/spaces/moonlit-circle/members',
      '/spaces/moonlit-circle/members/mem_abc123',
      '/spaces/moonlit-circle/events',
      '/spaces/moonlit-circle/events/evt_abc123',
      '/spaces/moonlit-circle/pathways',
      '/spaces/moonlit-circle/pathways/slowing-down',
      '/spaces/moonlit-circle/pathways/slowing-down/step-one',
      '/spaces/moonlit-circle/gathering-series/term-4',
    ]) {
      assert.equal(isTrackablePath(p), false, `${p} must not be tracked`)
    }
  })

  test('the two public Collective shapes are still tracked, and only those', () => {
    // The control. Without it, an allow-list that had quietly stopped
    // matching anything would pass every assertion above.
    assert.equal(isTrackablePath('/spaces/moonlit-circle/about'), true)
    assert.equal(
      isTrackablePath('/spaces/moonlit-circle/pathways/slowing-down/about'),
      true,
    )
  })

  test('token-bearing URLs are excluded whether the token is in path or query', () => {
    const token = 'a'.repeat(64)
    for (const p of [
      '/invites/8f3c1d9e4b7a2056',
      `/invites/${token}`,
      `/reset-password?token=${token}`,
      `/verify-email?token=${token}`,
      '/login?next=%2Fspaces%2Fmoonlit-circle%2Fcommunity',
    ]) {
      assert.equal(isTrackablePath(p), false, `${p} must not be tracked`)
    }
  })

  test('every private root above is refused, not merely unlisted', () => {
    for (const [, root] of PRIVATE) {
      assert.ok(
        __lists.NEVER_TRACKED.includes(root),
        `${root} should be in NEVER_TRACKED so no allow-list edit can reach it`,
      )
    }
  })
})
