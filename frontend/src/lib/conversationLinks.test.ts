import { strict as assert } from 'node:assert'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  channelPath,
  conversationPath,
  isSafeReturnPath,
  loginReturnPath,
} from './conversationLinks.ts'

const APP = join(process.cwd(), 'src', 'app')

/**
 * Turn a concrete path into the Next route directory it must resolve
 * to, so "does this URL have a page?" can be answered from the
 * filesystem rather than by reading the URL and nodding.
 */
function routeFileFor(path: string): string {
  const segments = path.replace(/^\//, '').split('?')[0].split('/')
  // /spaces/<slug>/community/<postId> → spaces/[slug]/community/[postId]
  const mapped = segments.map((seg, i) => {
    if (i === 1 && segments[0] === 'spaces') return '[slug]'
    if (i === 3 && segments[2] === 'community') return '[postId]'
    return seg
  })
  return join(APP, ...mapped, 'page.tsx')
}

describe('conversationPath', () => {
  it('addresses a single conversation', () => {
    assert.equal(
      conversationPath('moonlit-circle', 'cp_abc123'),
      '/spaces/moonlit-circle/community/cp_abc123',
    )
  })

  it('resolves to a route that actually exists', () => {
    // The bug this guards: an email can carry a tidy-looking URL to a
    // page that was never built. Checked against the filesystem, so
    // moving or renaming the route fails here.
    const file = routeFileFor(conversationPath('a-collective', 'cp_1'))
    assert.ok(
      existsSync(file),
      `no Next route for a conversation link — expected ${file}`,
    )
  })

  it('does not invent a channel segment', () => {
    // The post page resolves its own channel. A URL carrying one
    // would be a second route structure.
    const path = conversationPath('s', 'p')
    assert.equal(path.split('/').length, 5, path)
    assert.ok(!path.includes('/channels/'))
  })
})

describe('channelPath', () => {
  it('addresses the feed', () => {
    assert.equal(channelPath('moonlit-circle'), '/spaces/moonlit-circle/community')
  })

  it('resolves to a route that exists', () => {
    const file = join(APP, 'spaces', '[slug]', 'community', 'page.tsx')
    assert.ok(existsSync(file), file)
  })

  it('carries the channel as a query parameter, encoded', () => {
    assert.equal(
      channelPath('s', 'womens circle'),
      '/spaces/s/community?channel=womens%20circle',
    )
  })
})

describe('loginReturnPath', () => {
  it('uses the platform mechanism', () => {
    assert.equal(
      loginReturnPath('/spaces/moonlit-circle/community/cp_1'),
      '/login?next=%2Fspaces%2Fmoonlit-circle%2Fcommunity%2Fcp_1',
    )
  })

  it('round-trips through decoding', () => {
    const dest = conversationPath('moonlit-circle', 'cp_abc')
    const url = loginReturnPath(dest)
    const next = new URLSearchParams(url.split('?')[1]).get('next')
    assert.equal(next, dest)
  })
})

describe('isSafeReturnPath — mirrors the login form', () => {
  it('accepts a relative path', () => {
    assert.equal(isSafeReturnPath('/spaces/s/community/p'), true)
  })

  it('rejects an absolute URL', () => {
    assert.equal(isSafeReturnPath('https://evil.example/x'), false)
  })

  it('rejects a protocol-relative host', () => {
    assert.equal(isSafeReturnPath('//evil.example/x'), false)
    assert.equal(isSafeReturnPath('/\\evil.example'), false)
  })

  it('rejects nothing at all', () => {
    assert.equal(isSafeReturnPath(''), false)
    assert.equal(isSafeReturnPath(null), false)
    assert.equal(isSafeReturnPath(undefined), false)
  })
})

describe('the page guards in the right order', () => {
  it('redirects before it guards the area', () => {
    // Conversations is members-only, so a signed-out visitor's
    // `area_access` never contains it. If `requireArea` ran first it
    // would 404 them before the redirect — which is precisely why the
    // email button opened a 404. Asserted against the source because
    // the ordering is the fix, and a later edit could reverse it
    // without any test noticing.
    const page = join(
      APP, 'spaces', '[slug]', 'community', '[postId]', 'page.tsx',
    )
    const source = readFileSync(page, 'utf8')
    const redirectAt = source.indexOf('redirect(`/login?next=')
    const requireAt = source.indexOf("requireArea(space, 'conversations')")
    assert.ok(redirectAt > -1, 'the sign-in redirect is missing')
    assert.ok(requireAt > -1, 'the area guard is missing')
    assert.ok(
      redirectAt < requireAt,
      'requireArea runs before the redirect, so signed-out visitors 404',
    )
  })

  it('only redirects when unauthenticated', () => {
    // A signed-in member without access must still get notFound(),
    // not a login loop and not a disclosure.
    const page = join(
      APP, 'spaces', '[slug]', 'community', '[postId]', 'page.tsx',
    )
    const source = readFileSync(page, 'utf8')
    assert.ok(
      /if \(!me\) \{\s*\n\s*redirect\(`\/login\?next=/.test(source),
      'the redirect is not gated on an absent session',
    )
    assert.ok(
      source.includes('if (!post) notFound()'),
      'the unauthorised path no longer ends in notFound()',
    )
  })
})
