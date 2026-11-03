import { strict as assert } from 'node:assert'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  DEFAULT_RETURN_PATH,
  isSafeReturnPath,
  loginReturnFor,
} from './loginReturn.ts'

const SRC = join(process.cwd(), 'src')
const LAYOUT = join(SRC, 'app', 'spaces', '[slug]', 'layout.tsx')

describe('isSafeReturnPath', () => {
  it('accepts a relative path', () => {
    assert.equal(isSafeReturnPath('/spaces/embody/events/e_1'), true)
    assert.equal(isSafeReturnPath('/spaces/x/pathways/y'), true)
  })

  it('rejects an absolute URL', () => {
    for (const bad of [
      'https://evil.example/x',
      'http://evil.example',
      '//evil.example/x',
      '/\\evil.example',
      'javascript:alert(1)',
      'spaces/x',
    ]) {
      assert.equal(isSafeReturnPath(bad), false, bad)
    }
  })

  it('rejects nothing at all', () => {
    assert.equal(isSafeReturnPath(''), false)
    assert.equal(isSafeReturnPath(null), false)
    assert.equal(isSafeReturnPath(undefined), false)
  })
})

describe('loginReturnFor', () => {
  it('preserves the destination', () => {
    assert.equal(
      loginReturnFor('/spaces/embody/events/e_1'),
      '/login?next=%2Fspaces%2Fembody%2Fevents%2Fe_1',
    )
  })

  it('round-trips through decoding', () => {
    const dest = '/spaces/moonlit-circle/pathways/daring-heart'
    const next = new URLSearchParams(
      loginReturnFor(dest).split('?')[1],
    ).get('next')
    assert.equal(next, dest)
  })

  it('cannot be turned into an open redirect', () => {
    // The whole reason the header is validated rather than trusted.
    for (const hostile of [
      'https://evil.example/steal',
      '//evil.example/steal',
      '/\\evil.example',
    ]) {
      const url = loginReturnFor(hostile)
      const next = new URLSearchParams(url.split('?')[1]).get('next')
      assert.equal(next, DEFAULT_RETURN_PATH, hostile)
      assert.ok(!url.includes('evil.example'), url)
    }
  })

  it('falls back rather than throwing on an absent path', () => {
    assert.equal(
      loginReturnFor(null, { fallback: '/spaces/embody' }),
      '/login?next=%2Fspaces%2Fembody',
    )
  })

  it('honours a different login door', () => {
    assert.equal(
      loginReturnFor('/admin/thing', { loginPath: '/admin/login' }),
      '/admin/login?next=%2Fadmin%2Fthing',
    )
  })
})

describe('the proxy writes the path rather than forwarding it', () => {
  const proxy = () => readFileSync(join(SRC, 'proxy.ts'), 'utf8')

  it('sets x-pathname from the request URL', () => {
    const source = proxy()
    assert.ok(
      /forwardHeaders\.set\('x-pathname', pathname\)/.test(source),
      'x-pathname is no longer written from the request pathname',
    )
    assert.ok(
      /const \{ pathname \} = request\.nextUrl/.test(source),
      'pathname no longer comes from the URL',
    )
  })

  it('uses set, not append, so a client value is replaced', () => {
    // `new Headers(request.headers)` copies what the client sent; only
    // `.set` guarantees ours wins. `.append` would leave both, and the
    // first one read could be theirs.
    const source = proxy()
    assert.ok(!/forwardHeaders\.append\('x-pathname'/.test(source))
  })

  it('the matcher still covers Collective pages', () => {
    // If /spaces stopped going through the proxy, x-pathname would be
    // whatever the client sent — which is why it is validated.
    //
    // Asserted on the matcher's shape rather than by compiling it:
    // the source text carries escaped backslashes, so rebuilding the
    // regex from it tests my unescaping, not the matcher.
    const source = proxy()
    const match = source.match(/matcher:\s*\[\s*'([^']+)'/)
    assert.ok(match, 'no matcher found')
    const matcher = match![1]
    assert.ok(
      matcher.startsWith('/((?!'),
      'the matcher is no longer a catch-all with exclusions',
    )
    assert.ok(matcher.includes('api/'), 'api/ is no longer excluded')
    assert.ok(
      !matcher.includes('spaces'),
      '/spaces is now excluded from the proxy — x-pathname would be '
      + 'client-supplied there',
    )
  })
})

describe('the Collective layout distinguishes the three cases', () => {
  const layout = () => readFileSync(LAYOUT, 'utf8')

  it('exists where expected', () => {
    assert.ok(existsSync(LAYOUT), LAYOUT)
  })

  it('redirects only when there is no user', () => {
    const source = layout()
    assert.ok(
      /if \(!space\) \{[\s\S]*?if \(!user\) \{[\s\S]*?redirect\(loginReturnFor/.test(source),
      'the redirect is not gated on an absent session',
    )
  })

  it('still 404s a signed-in visitor', () => {
    // Structure, not text position: the earlier version of this test
    // searched for "notFound()" and found it in a comment above the
    // redirect, which is the kind of false signal a position check
    // invites.
    //
    // The shape required is: inside `if (!space)`, a `!user` block
    // that redirects, and a `notFound()` statement *outside* that
    // block so an authenticated visitor still gets a 404.
    const source = layout().replace(/\/\/[^\n]*/g, '')
    const branch = source.slice(source.indexOf('if (!space) {'))
    const redirectAt = branch.indexOf('redirect(loginReturnFor')
    const notFoundAt = branch.indexOf('notFound()')
    assert.ok(redirectAt > -1, 'the signed-out redirect is gone')
    assert.ok(notFoundAt > -1, 'the signed-in 404 is gone')
    assert.ok(
      notFoundAt > redirectAt,
      'notFound() now runs before the signed-out redirect, so a member '
      + 'who is simply not signed in gets a 404 again',
    )
    assert.ok(
      branch.indexOf('if (!user)') < redirectAt,
      'the redirect is no longer gated on an absent session',
    )
  })

  it('does not redirect when the Collective resolved', () => {
    // Public Collectives must open anonymously. The redirect lives
    // inside the `!space` branch and nowhere else.
    const source = layout()
    const occurrences = source.split('redirect(loginReturnFor').length - 1
    assert.equal(occurrences, 1, 'more than one redirect site')
    const before = source.slice(0, source.indexOf('redirect(loginReturnFor'))
    assert.ok(
      before.lastIndexOf('if (!space) {') > before.lastIndexOf('return ('),
      'the redirect is not inside the unresolved-Collective branch',
    )
  })

  it('validates the header rather than using it raw', () => {
    const source = layout()
    assert.ok(
      /loginReturnFor\(requested/.test(source),
      'the header value is not passed through the validator',
    )
    assert.ok(
      !/next=\$\{requested\}/.test(source),
      'the header is interpolated into a URL directly',
    )
  })
})

describe('private and missing Collectives are indistinguishable', () => {
  it('both reach the same branch', () => {
    // `getSpace` returns null for a private Collective viewed
    // anonymously AND for a slug that does not exist; the public
    // About fallback returns null for both too. So one branch serves
    // both, and an anonymous visitor cannot tell them apart — no
    // enumeration of private Collectives.
    //
    // Asserted on the source because the alternative — a per-case
    // redirect — is exactly the disclosure this design avoids, and it
    // would be an easy "improvement" for somebody to add later.
    const source = readFileSync(LAYOUT, 'utf8')
    const branch = source.slice(
      source.indexOf('if (!space) {'),
      source.indexOf('notFound()', source.indexOf('if (!space) {')),
    )
    for (const leak of ['404', 'does not exist', 'private', 'exists']) {
      assert.ok(
        !new RegExp(`${leak}\\s*\\?`).test(branch),
        `the branch appears to distinguish cases on ${leak}`,
      )
    }
  })
})
