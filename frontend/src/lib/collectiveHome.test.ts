import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { buildTiles } from './collectiveHomeTiles.ts'
import type { SpaceResponse } from '../types/platform.ts'

/**
 * The Collective Home's tile rules.
 *
 * The product rule being defended: the Home is an orientation hub, so
 * a real member area keeps its tile whether or not it is busy today. A
 * Gatherings tile that vanished between terms would read as broken and
 * would strand the member with no route to the archive. Only an area
 * the platform itself can switch off — the member directory — may
 * disappear.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

function space(over: Partial<SpaceResponse> = {}): SpaceResponse {
  return {
    slug: 'embody',
    name: 'EMBODY',
    pathways: [],
    show_member_directory: true,
    learner_count: 0,
    leader_count: 0,
    upcoming_gathering_count: 0,
    next_gathering_starts_at: null,
    ...over,
  } as unknown as SpaceResponse
}

const keys = (s: SpaceResponse) => buildTiles(s).map((t) => t.key)

describe('tile set', () => {
  test('a fully-populated Collective shows all five', () => {
    assert.deepEqual(keys(space()), [
      'gatherings', 'pathways', 'conversations', 'members', 'about',
    ])
  })

  test('Members disappears when the directory is switched off', () => {
    const k = keys(space({ show_member_directory: false }))
    assert.ok(!k.includes('members'))
    assert.deepEqual(k, ['gatherings', 'pathways', 'conversations', 'about'])
  })

  test('About is always present', () => {
    assert.ok(keys(space({ show_member_directory: false })).includes('about'))
  })

  test('an empty Collective still shows every destination', () => {
    // The defect this prevents: hiding a whole member area because its
    // count happens to be zero this week.
    const k = keys(space({
      pathways: [], upcoming_gathering_count: 0, learner_count: 0, leader_count: 0,
    }))
    assert.ok(k.includes('gatherings'))
    assert.ok(k.includes('pathways'))
    assert.ok(k.includes('conversations'))
  })
})

describe('live context', () => {
  const metaFor = (s: SpaceResponse, key: string) =>
    buildTiles(s).find((t) => t.key === key)?.meta

  test('zero gatherings reads as a calm fact, not an absence', () => {
    assert.equal(metaFor(space(), 'gatherings'), 'No upcoming gatherings')
  })

  test('gatherings show the count and the next date', () => {
    const meta = metaFor(
      space({ upcoming_gathering_count: 12, next_gathering_starts_at: '2026-10-05T07:00:00' }),
      'gatherings',
    )
    assert.match(meta ?? '', /^12 upcoming · next /)
  })

  test('a count with no next date degrades to the count alone', () => {
    assert.equal(
      metaFor(space({ upcoming_gathering_count: 3, next_gathering_starts_at: null }), 'gatherings'),
      '3 upcoming',
    )
  })

  test('one gathering is not pluralised into nonsense', () => {
    assert.match(
      metaFor(space({ upcoming_gathering_count: 1 }), 'gatherings') ?? '', /^1 upcoming/,
    )
  })

  test('zero pathways says so rather than showing nothing', () => {
    assert.equal(metaFor(space(), 'pathways'), 'No pathways available yet')
  })

  test('pathways pluralise correctly', () => {
    const one = space({ pathways: [{}] as never })
    const many = space({ pathways: [{}, {}, {}] as never })
    assert.equal(metaFor(one, 'pathways'), '1 pathway available')
    assert.equal(metaFor(many, 'pathways'), '3 pathways available')
  })

  test('Conversations carries no metric in v1', () => {
    assert.equal(metaFor(space(), 'conversations'), null)
  })

  test('About carries no metric', () => {
    assert.equal(metaFor(space(), 'about'), null)
  })

  test('members combine learners and leaders, and stay quiet at zero', () => {
    assert.equal(metaFor(space({ learner_count: 9, leader_count: 2 }), 'members'), '11 members')
    assert.equal(metaFor(space({ learner_count: 1, leader_count: 0 }), 'members'), '1 member')
    assert.equal(metaFor(space(), 'members'), null)
  })
})

describe('tile links', () => {
  test('each tile points at its real member area', () => {
    const byKey = Object.fromEntries(buildTiles(space()).map((t) => [t.key, t.href]))
    assert.equal(byKey.gatherings, '/spaces/embody/events')
    assert.equal(byKey.pathways, '/spaces/embody/pathways')
    assert.equal(byKey.conversations, '/spaces/embody/community')
    assert.equal(byKey.members, '/spaces/embody/members')
    assert.equal(byKey.about, '/spaces/embody/about')
  })

  test('every tile has a description and a call to action', () => {
    for (const tile of buildTiles(space())) {
      assert.ok(tile.description.length > 0, tile.key)
      assert.ok(tile.cta.length > 0, tile.key)
    }
  })
})

describe('route + theme contract', () => {
  const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

  test('non-members are sent to the public About page', () => {
    const src = read('app/spaces/[slug]/page.tsx')
    assert.ok(src.includes('redirect(`/spaces/${slug}/about`)'))
    assert.ok(src.includes('const isMember = memberships.some'))
    // Membership is the key — not a role check that would let an
    // administrator into a member-only surface.
    assert.ok(!/role\s*===\s*['"]admin['"]/.test(src))
  })

  test('there is no separate /home route', () => {
    const src = read('app/spaces/[slug]/page.tsx')
    assert.ok(!src.includes("redirect(`/spaces/${slug}/home`)"))
  })

  test('the card CTA takes the Collective palette, not platform teal', () => {
    const src = read('components/collective/AtlasCard.tsx')
    assert.ok(src.includes("var(--fc-accent, #38A09E)"))
    assert.ok(!src.includes("style={{ color: '#38A09E' }}"))
  })

  test('the Home introduces no theme logic of its own', () => {
    const src = read('components/collective/CollectiveHome.tsx')
    // Naming the provider in a comment is fine and useful; importing
    // or rendering a second one would mean duplicated theme logic.
    assert.ok(!/import .*CollectiveThemeProvider/.test(src))
    assert.ok(!src.includes('<CollectiveThemeProvider'))
    assert.ok(src.includes('var(--fc-accent-ring'), 'focus ring should be themed')
  })

  test('artwork falls back rather than rendering an empty box', () => {
    const src = read('components/collective/CollectiveHome.tsx')
    assert.ok(src.includes('getCollectiveCoverStyle(space.slug)'))
    assert.ok(src.includes('cover_image_url'))
  })

  test('images are lazy, sized, and meaningfully described', () => {
    const card = read('components/collective/AtlasCard.tsx')
    assert.ok(card.includes("loading={priority ? undefined : 'lazy'}"))
    assert.ok(card.includes('width={1200}') && card.includes('height={800}'))
    const home = read('components/collective/CollectiveHome.tsx')
    assert.ok(home.includes('alt={`${tile.name} at ${space.name}`}'))
  })

  test('the grid is one / two / three columns', () => {
    const src = read('components/collective/CollectiveHome.tsx')
    assert.ok(src.includes('grid-cols-1'))
    assert.ok(src.includes('sm:grid-cols-2'))
    assert.ok(src.includes('lg:grid-cols-3'))
  })

  test('the dashboard Collective card lands on the Home', () => {
    const src = read('app/dashboard/page.tsx')
    assert.ok(src.includes('href={`/spaces/${card.membership.space_slug}`}'))
    assert.ok(!src.includes('href={`/spaces/${card.membership.space_slug}/community`}'))
  })
})
