import { strict as assert } from 'node:assert'
import { describe, it } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  PRIVATE_ONLY_FIELDS,
  PUBLIC_ABOUT_CTA_HREF,
  PUBLIC_ABOUT_CTA_LABEL,
  publicAboutAsSpace,
} from './publicCollectiveAbout.ts'
import type { PublicCollectiveAbout } from '../types/platform.ts'

const SRC = dirname(dirname(fileURLToPath(import.meta.url)))
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const about: PublicCollectiveAbout = {
  slug: 'world-builders',
  name: 'World Builders',
  tagline: 'Learn. Build. Belong.',
  description: 'The shared home for Fresh Collective Creators.',
  about_content: '<h2>Our Story</h2><p>Every collective has one.</p>',
  cover_image_url: '/api/uploads/cover.webp',
  logo_url: null,
  location_hero_artwork_url: '/api/uploads/island-hero.webp',
  location_thumbnail_artwork_url: '/api/uploads/island-thumb.webp',
  location_name: 'Island Sanctuary',
  themes: ['Creativity', 'Leadership'],
  creator_name: 'Lindsey',
  creator_only: true,
}

describe('the public About payload, as the page reads it', () => {
  it('carries the Collective’s own identity', () => {
    const s = publicAboutAsSpace(about)
    assert.equal(s.slug, 'world-builders')
    assert.equal(s.name, 'World Builders')
    assert.equal(s.tagline, 'Learn. Build. Belong.')
    assert.equal(s.about_content, '<h2>Our Story</h2><p>Every collective has one.</p>')
    assert.equal(s.cover_image_url, '/api/uploads/cover.webp')
    assert.equal(s.creator_name, 'Lindsey')
  })

  it('carries the Location artwork so the page looks like itself', () => {
    const s = publicAboutAsSpace(about)
    assert.equal(s.location?.hero_artwork_url, '/api/uploads/island-hero.webp')
    assert.equal(s.location?.thumbnail_artwork_url, '/api/uploads/island-thumb.webp')
    assert.equal(s.location?.name, 'Island Sanctuary')
  })

  it('omits the Location entirely when there is none', () => {
    const s = publicAboutAsSpace({
      ...about,
      location_hero_artwork_url: null,
      location_thumbnail_artwork_url: null,
      location_name: null,
    })
    assert.equal(s.location, null)
  })

  it('reports the Collective as creator-managed, which drives the CTA', () => {
    assert.equal(publicAboutAsSpace(about).auto_grant_role, 'creator')
    assert.equal(
      publicAboutAsSpace({ ...about, creator_only: false }).auto_grant_role,
      null,
    )
  })
})

describe('what the public About payload refuses to carry', () => {
  // The requirement, asserted on the value rather than on the type:
  // a type can be widened, a null cannot be misread.
  const s = publicAboutAsSpace(about) as unknown as Record<string, unknown>

  it('carries no member-only guidance', () => {
    for (const field of [
      'guidance_start_body', 'guidance_focus_body', 'guidance_links_body',
      'guidance_start_title', 'guidance_focus_title', 'guidance_links_title',
    ]) {
      assert.equal(s[field], null, `${field} must be null`)
    }
  })

  it('carries no welcome or identity copy written for members', () => {
    assert.equal(s.welcome_message, null)
    assert.equal(s.identity_statement, null)
  })

  it('carries no protected Pathways', () => {
    assert.deepEqual(s.pathways, [])
  })

  it('carries no membership data', () => {
    assert.equal(s.learner_count, 0)
    assert.equal(s.leader_count, 0)
    assert.equal(s.show_member_directory, false)
  })

  it('offers no member tabs in the nav', () => {
    // The leak this release nearly shipped: ``SpaceNav`` reads
    // ``reachableAreas === undefined`` as "show every tab", so an
    // absent ``area_access`` rendered Pathways, Gatherings,
    // Conversations, Messages and Members for a public visitor to a
    // private Collective. They all refuse on click, but offering a
    // door that cannot open is what "the About page must not become a
    // doorway" means.
    assert.deepEqual(s.area_access, [])
    assert.notEqual(s.area_access, undefined)
  })

  it('carries no joining doors', () => {
    // There is no public joining here — ``join_space`` and
    // ``request_access`` both answer 403 for this Collective.
    assert.equal(s.joining_options, undefined)
  })

  it('carries no internal identifier', () => {
    assert.equal(s.id, '')
    assert.equal(s.location?.['id' as never], '')
  })

  it('every field named in PRIVATE_ONLY_FIELDS is empty or absent', () => {
    // One list, one loop — so adding a name to the list is enough and
    // a new private field cannot be half-covered.
    for (const field of PRIVATE_ONLY_FIELDS) {
      const v = s[field]
      const empty =
        v === null || v === undefined || v === 0 || v === false
        || (Array.isArray(v) && v.length === 0)
      assert.ok(empty, `${field} should be empty, got ${JSON.stringify(v)}`)
    }
  })

  it('no value smuggles member-only text through', () => {
    const hostile = publicAboutAsSpace({
      ...about,
      // The server allowlist cannot send these at all; this proves the
      // adapter would not pass them on even if the shape changed.
      ...({ guidance_start_body: 'MEMBERS-ONLY', welcome_message: 'MEMBERS-ONLY' } as never),
    })
    assert.ok(!JSON.stringify(hostile).includes('MEMBERS-ONLY'))
  })
})

describe('the visitor call to action', () => {
  it('is the approved copy and destination', () => {
    assert.equal(PUBLIC_ABOUT_CTA_LABEL, 'Explore Becoming a Creator →')
    assert.equal(PUBLIC_ABOUT_CTA_HREF, '/for-creators')
  })

  it('the About CTA panel renders it for a creator-only Collective', () => {
    const src = read('app/spaces/[slug]/about/SpaceAboutCTA.tsx')
    assert.match(src, /PUBLIC_ABOUT_CTA_HREF/)
    assert.match(src, /PUBLIC_ABOUT_CTA_LABEL/)
    // Still inside the auto-grant, non-member branch — members fall
    // through to "Enter collective".
    const at = src.indexOf('if (autoGrantRole && !isMember)')
    assert.ok(at > 0, 'the auto-grant branch is still the gate')
    assert.ok(src.indexOf('PUBLIC_ABOUT_CTA_HREF', at) > at)
  })

  it('offers no join or request-access action there', () => {
    // Both endpoints refuse these Collectives outright, so either
    // button would be one that cannot work. Checked on the affordance
    // rather than the word: this file legitimately discusses joining.
    const src = read('app/spaces/[slug]/about/SpaceAboutCTA.tsx')
    const at = src.indexOf('if (autoGrantRole && !isMember)')
    const branch = src.slice(at, src.indexOf('// Already a member', at))
    assert.ok(!/href=\{?["'`]\/api\/spaces/.test(branch))
    assert.ok(!/request-access/.test(branch))
    assert.ok(!/onClick/.test(branch), 'no action button in this branch')
  })
})

describe('the About page falls back without relaxing the private gate', () => {
  const page = () => read('app/spaces/[slug]/about/page.tsx')

  it('it tries the private payload first', () => {
    const src = page()
    const priv = src.indexOf('getSpace(slug)')
    const pub = src.indexOf('getPublicCollectiveAbout(slug)')
    assert.ok(priv > 0 && pub > priv, 'public is the fallback, not the default')
  })

  it('the fallback only runs when the private payload is unavailable', () => {
    assert.match(page(), /privateSpace \? null : await getPublicCollectiveAbout/)
  })

  it('the public page is indexable, and others still are not', () => {
    const src = page()
    // generateMetadata resolves the public payload too, so the name
    // reaches the markup for a discoverable Collective...
    assert.match(src, /getPublicCollectiveAbout\(slug\)/)
    // ...and still returns noindex when neither payload resolves.
    assert.match(src, /robots: \{ index: false, follow: false \}/)
  })

  it('it does not reach for the full private response as a fallback', () => {
    // The thing the brief ruled out: no second getSpace call with
    // different credentials, and no server-side bypass.
    const src = page()
    assert.equal((src.match(/getSpace\(slug\)/g) ?? []).length, 2,
      'once in generateMetadata, once in the page — no third path')
  })
})


describe('the Collective layout falls back too', () => {
  const layout = () => read('app/spaces/[slug]/layout.tsx')

  it('it tries the private payload first, then the public one', () => {
    const src = layout()
    const priv = src.indexOf('getSpace(slug)')
    const pub = src.indexOf('getPublicCollectiveAbout(slug)')
    assert.ok(priv > 0 && pub > priv, 'public is the fallback, not the default')
  })

  it('without this the whole route 404s', () => {
    // The layout wraps the About page, so its ``notFound()`` fired
    // before the page could render — the page produced correct markup
    // and the response was still a 404. Found in production
    // verification, not in the suite.
    const src = layout()
    assert.match(src, /privateSpace \? null : await getPublicCollectiveAbout/)
    assert.match(src, /if \(!space\) notFound\(\)/)
  })

  it('it reads the same adapter as the page, not its own', () => {
    assert.match(layout(), /publicAboutAsSpace/)
  })
})
