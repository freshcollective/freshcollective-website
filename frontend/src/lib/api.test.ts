/**
 * Unit tests for the shared media/asset URL resolver.
 *
 * The resolver's job after the same-origin-media fix is to make every
 * browser-visible asset URL either external (``http(s)://…`` passed
 * through) or same-origin (``/api/uploads/…`` returned as a relative
 * path). Never returns an absolute URL against ``NEXT_PUBLIC_API_URL``
 * because that would defeat the ``SameSite=Lax`` cookie flow that
 * private-media serving depends on.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping:
 *
 *   node --experimental-strip-types --test src/lib/api.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path
import { resolveMediaUrl } from './api.ts'


describe('resolveMediaUrl — nullish', () => {
  test('null → null', () => {
    assert.equal(resolveMediaUrl(null), null)
  })
  test('undefined → null', () => {
    assert.equal(resolveMediaUrl(undefined), null)
  })
  test('empty string → null', () => {
    assert.equal(resolveMediaUrl(''), null)
  })
})


describe('resolveMediaUrl — external URLs pass through verbatim', () => {
  test('https URL is returned unchanged (YouTube embed etc.)', () => {
    const url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    assert.equal(resolveMediaUrl(url), url)
  })
  test('http URL is returned unchanged', () => {
    const url = 'http://example.com/image.png'
    assert.equal(resolveMediaUrl(url), url)
  })
  test('R2 public bucket URL is returned unchanged', () => {
    const url = 'https://pub-xyz.r2.dev/platform-artwork/hero.png'
    assert.equal(resolveMediaUrl(url), url)
  })
})


describe('resolveMediaUrl — absolute /api/uploads/... stays same-origin', () => {
  test('private pathway image → same-origin relative', () => {
    // The regression this test guards against: previously this
    // returned ``https://fc-api-…/api/uploads/media/embody/xxx.png``
    // which failed the SameSite=Lax cookie check when fc-api and
    // fc-web are on distinct sites under the Public Suffix List.
    const path = '/api/uploads/media/embody/uuid_the_embody_arc.png'
    assert.equal(resolveMediaUrl(path), path)
  })

  test('Space cover URL stays same-origin', () => {
    const path = '/api/uploads/covers/uuid_cover.png'
    assert.equal(resolveMediaUrl(path), path)
  })

  test('Space logo URL stays same-origin', () => {
    const path = '/api/uploads/logos/embody/uuid_logo.png'
    assert.equal(resolveMediaUrl(path), path)
  })

  test('Pathway cover URL stays same-origin', () => {
    const path = '/api/uploads/pathway-covers/uuid_cover.png'
    assert.equal(resolveMediaUrl(path), path)
  })

  test('CreatorMediaAsset file_url stays same-origin', () => {
    // Matches the shape ``save_media_file`` writes: ``/api/uploads/media/{slug}/…``.
    const path = '/api/uploads/media/moonlit-circle/uuid_MC_logo.png'
    assert.equal(resolveMediaUrl(path), path)
  })

  test('SpaceResource / step-resource URL stays same-origin', () => {
    const path = '/api/uploads/steps/step-id/uuid_resource.pdf'
    assert.equal(resolveMediaUrl(path), path)
  })

  test('user avatar URL stays same-origin', () => {
    const path = '/api/uploads/avatars/uuid_avatar.jpg'
    assert.equal(resolveMediaUrl(path), path)
  })
})


describe('resolveMediaUrl — public platform-artwork/* continues to work', () => {
  test('platform-artwork URL stays same-origin so the proxy forwards to the public fc-api route', () => {
    // fc-api's ``/api/uploads/platform-artwork/{path}`` route serves
    // WITHOUT auth (302 → public R2 origin). Routing through the
    // same-origin proxy still works — the proxy just passes the 302
    // through and the browser follows to R2 direct.
    const path = '/api/uploads/platform-artwork/atlas-locations/moon-lagoon/uuid_hero.png'
    assert.equal(resolveMediaUrl(path), path)
  })

  test('platform-artwork Physical Location URL stays same-origin', () => {
    const path = '/api/uploads/platform-artwork/place-artwork/melbourne/uuid_hero.png'
    assert.equal(resolveMediaUrl(path), path)
  })
})


describe('resolveMediaUrl — bare storage keys get the /api/uploads/ prefix', () => {
  test('bare "media/…" key → same-origin /api/uploads/media/…', () => {
    assert.equal(
      resolveMediaUrl('media/embody/uuid_x.png'),
      '/api/uploads/media/embody/uuid_x.png',
    )
  })

  test('bare "avatars/…" key → same-origin /api/uploads/avatars/…', () => {
    assert.equal(
      resolveMediaUrl('avatars/uuid_avatar.jpg'),
      '/api/uploads/avatars/uuid_avatar.jpg',
    )
  })

  test('bare "platform-artwork/…" key gets /api/uploads/ prefix (same-origin, public path)', () => {
    assert.equal(
      resolveMediaUrl('platform-artwork/hero/uuid_x.png'),
      '/api/uploads/platform-artwork/hero/uuid_x.png',
    )
  })
})


describe('resolveMediaUrl — never returns an absolute fc-api URL', () => {
  // Guardrail: whatever env var machinery evolves, this function must
  // NEVER return a URL of the form ``https?://…/api/uploads/…`` for
  // an internal upload. The Same-Site cookie flow depends on the
  // request being same-origin. External URLs (http(s)://…) are the
  // only case where the resolver returns a non-relative string, and
  // those are always caller-supplied external references.
  test('a same-origin absolute path never gets rewritten to an absolute URL', () => {
    const out = resolveMediaUrl('/api/uploads/media/embody/x.png')
    assert.ok(out !== null)
    assert.ok(
      !out.startsWith('http://') && !out.startsWith('https://'),
      `expected relative path, got ${out}`,
    )
  })

  test('a bare storage key never gets rewritten to an absolute URL', () => {
    const out = resolveMediaUrl('media/embody/x.png')
    assert.ok(out !== null)
    assert.ok(
      !out.startsWith('http://') && !out.startsWith('https://'),
      `expected relative path, got ${out}`,
    )
  })
})
