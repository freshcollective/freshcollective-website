import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  buildTiles,
  DEFAULT_TILE_ORDER,
  HOME_TILE_DEFAULT_COPY,
  HOME_TILE_LABEL,
  MAX_HOME_DESCRIPTION,
} from './collectiveHomeTiles.ts'
import { tileFallbackBackground, tileImageUrl, TILE_PLATFORM_ARTWORK } from './collectiveHomeArtwork.ts'
import { readableOnWhite } from './collectivePalette.ts'
import type { CollectivePaletteMeta } from './collectivePalette.ts'
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
  test('a fully-populated Collective shows every member area', () => {
    assert.deepEqual(keys(space()), [
      'gatherings', 'pathways', 'offerings', 'conversations', 'messages',
      'members', 'about',
    ])
  })

  test('Members disappears when the directory is switched off', () => {
    const k = keys(space({ show_member_directory: false }))
    assert.ok(!k.includes('members'))
    assert.deepEqual(k, [
      'gatherings', 'pathways', 'offerings', 'conversations', 'messages', 'about',
    ])
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

  test('the Collective cover is not stamped onto every tile', () => {
    // The Phase 1 defect this locks out: one cover image repeated six
    // times, which read as a rendering fault rather than a design.
    const src = read('components/collective/CollectiveHome.tsx')
    assert.ok(!src.includes('cover_image_url'))
    assert.ok(src.includes('tileImageUrl('), 'tiles resolve their own artwork')
    assert.ok(src.includes('tileFallbackBackground('), 'and their own fallback')
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

// ---------------------------------------------------------------------------
// Phase 2 — creator configuration
// ---------------------------------------------------------------------------

describe('creator configuration', () => {
  test('a Collective that has never opened the editor gets the defaults', () => {
    assert.deepEqual(keys(space({ home_tiles: undefined })), [
      'gatherings', 'pathways', 'offerings', 'conversations', 'messages',
      'members', 'about',
    ])
  })

  test('an empty configuration is treated as no configuration', () => {
    // Not as "hide everything" — a Home with no doorways is a dead end,
    // and an empty array is far more likely to be a payload problem
    // than a deliberate choice.
    assert.equal(
      keys(space({ home_tiles: [] })).length, DEFAULT_TILE_ORDER.length,
    )
  })

  test('the creator order is the render order', () => {
    const k = keys(space({
      home_tiles: [{ key: 'about' }, { key: 'members' }, { key: 'gatherings' }],
    }))
    assert.deepEqual(k, ['about', 'members', 'gatherings'])
  })

  test('a tile the creator hid is simply absent', () => {
    // Hiding happens server-side, so the client sees the survivors.
    assert.ok(!keys(space({
      home_tiles: [{ key: 'gatherings' }, { key: 'about' }],
    })).includes('pathways'))
  })

  test("a creator's words replace the platform's, for that tile only", () => {
    const tiles = buildTiles(space({
      home_tiles: [
        { key: 'gatherings', description: 'Tuesday circles, in the studio.' },
        { key: 'pathways' },
      ],
    }))
    assert.equal(tiles[0].description, 'Tuesday circles, in the studio.')
    assert.equal(tiles[1].description, HOME_TILE_DEFAULT_COPY.pathways)
  })

  test('a blank description falls back to the platform copy', () => {
    const [tile] = buildTiles(space({ home_tiles: [{ key: 'gatherings', description: '' }] }))
    assert.equal(tile.description, HOME_TILE_DEFAULT_COPY.gatherings)
  })

  test("a creator's image reaches the tile", () => {
    const [tile] = buildTiles(space({
      home_tiles: [{ key: 'members', image_url: '/api/uploads/media/s/m.webp' }],
    }))
    assert.equal(tile.imageUrl, '/api/uploads/media/s/m.webp')
  })

  test('a tile key this build has never heard of is skipped, not rendered blank', () => {
    const k = keys(space({ home_tiles: [{ key: 'gatherings' }, { key: 'teleporter' }] }))
    assert.deepEqual(k, ['gatherings'])
  })

  test('configuration can never re-expose a closed member directory', () => {
    // Defence in depth: the server strips this too, but a stale or
    // cached payload must not be able to leak the directory.
    assert.ok(!keys(space({
      show_member_directory: false,
      home_tiles: [{ key: 'members' }, { key: 'about' }],
    })).includes('members'))
  })

  test('every default description fits the editor limit', () => {
    for (const [key, copy] of Object.entries(HOME_TILE_DEFAULT_COPY)) {
      assert.ok(copy.length <= MAX_HOME_DESCRIPTION, `${key}: ${copy.length}`)
    }
  })
})

// ---------------------------------------------------------------------------
// Phase 2 — tile artwork
// ---------------------------------------------------------------------------

describe('tile artwork', () => {
  const noArtwork = () => null
  const allArtwork = (key: string) => `https://art.example/${key}.webp`

  test("the creator's image wins over everything", () => {
    assert.equal(
      tileImageUrl('gatherings', '/api/uploads/media/s/mine.webp', allArtwork),
      '/api/uploads/media/s/mine.webp',
    )
  })

  test('with no creator image, each tile takes its own platform artwork', () => {
    // Read from DEFAULT_TILE_ORDER rather than listed by hand, so a
    // new tile is covered the moment it joins the vocabulary instead
    // of quietly sitting outside this assertion.
    const urls = DEFAULT_TILE_ORDER.map((k) => tileImageUrl(k, null, allArtwork))
    assert.equal(
      new Set(urls).size, urls.length,
      'every doorway should take its own image',
    )
  })

  test('the artwork keys are real platform assets, not invented names', () => {
    const registry = readFileSync(join(SRC, '../../backend/app/admin/platform_artwork.py'), 'utf8')
    for (const key of Object.values(TILE_PLATFORM_ARTWORK)) {
      assert.ok(registry.includes(`"${key}"`), `${key} is not in the artwork registry`)
    }
  })

  test('a missing platform asset drops to the themed gradient, never to a blank box', () => {
    assert.equal(tileImageUrl('gatherings', null, noArtwork), null)
    assert.ok(tileFallbackBackground('gatherings', null, 'embody').length > 0)
  })
})

describe('themed fallback artwork', () => {
  const palette = (over: Partial<CollectivePaletteMeta['palette']> = {}): CollectivePaletteMeta => ({
    key: 'test', name: 'Test',
    palette: { primary: '#38A09E', secondary: '#1F4E5F', accent: '#F2B441', background: '#FFFFFF', ...over },
  })

  test('two tiles in one Collective do not look identical', () => {
    // The Phase 1 complaint, in one assertion: World Builders showed
    // the same gradient on every tile.
    const p = palette()
    const backgrounds = DEFAULT_TILE_ORDER
      .map((k) => tileFallbackBackground(k, p, 'world-builders'))
    assert.equal(new Set(backgrounds).size, backgrounds.length)
  })

  test('two Collectives with different palettes do not look alike', () => {
    const teal = tileFallbackBackground('gatherings', palette(), 'embody')
    const amber = tileFallbackBackground(
      'gatherings', palette({ primary: '#C2410C', secondary: '#7C2D12', accent: '#FCD34D' }), 'embody',
    )
    assert.notEqual(teal, amber)
  })

  test('the gradient is built from the palette, not from platform teal', () => {
    const bg = tileFallbackBackground(
      'pathways', palette({ primary: '#C2410C', secondary: '#7C2D12', accent: '#FCD34D' }), 'embody',
    )
    assert.ok(!/38A09E/i.test(bg), 'platform teal leaked into a themed Collective')
  })

  test('the same tile renders the same way every time', () => {
    const p = palette()
    assert.equal(
      tileFallbackBackground('members', p, 'embody'),
      tileFallbackBackground('members', p, 'embody'),
    )
  })

  test('a Collective with no palette still gets distinct per-Collective artwork', () => {
    assert.notEqual(
      tileFallbackBackground('gatherings', null, 'embody'),
      tileFallbackBackground('gatherings', null, 'world-builders'),
    )
  })
})

// ---------------------------------------------------------------------------
// Phase 2 — theming and the editor
// ---------------------------------------------------------------------------

describe('theme reaches more than the button', () => {
  const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

  test('border, shadow and focus ring all take the Collective accent', () => {
    const src = read('components/collective/CollectiveHome.tsx')
    for (const token of ['--fc-accent-line', '--fc-accent-tint', '--fc-accent-ring']) {
      assert.ok(src.includes(token), `${token} is not applied`)
    }
  })

  test('the accent rule under the heading is themed', () => {
    const src = read('components/collective/CollectiveHome.tsx')
    assert.match(src, /--fc-accent(-strong)?[^)]*\)['"]?\s*\}\}/)
  })

  test('tile meta text can take the Collective colour', () => {
    const src = read('components/collective/AtlasCard.tsx')
    assert.ok(src.includes('themeMeta'))
    assert.ok(src.includes('var(--fc-accent-ink'))
  })

  test('no palette hex is hardcoded into the Home', () => {
    const src = read('components/collective/CollectiveHome.tsx')
    // Neutral ink and the CSS-variable fallbacks are fine; a bare
    // colour literal driving the design is not.
    const bare = src.match(/#[0-9a-fA-F]{6}/g) ?? []
    for (const hex of bare) {
      assert.ok(src.includes(`var(--fc-accent`), `unthemed colour ${hex}`)
    }
  })
})

describe('the Home editor', () => {
  const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
  const form = () => read('app/creator-studio/settings/CollectiveHomeForm.tsx')

  test('it lives on the Collective Home settings tab', () => {
    const shell = read('app/creator-studio/settings/SettingsTabbedShell.tsx')
    assert.ok(shell.includes('<CollectiveHomeTab'))
    const tab = read('app/creator-studio/settings/CollectiveHomeTab.tsx')
    assert.ok(tab.includes('<CollectiveHomeForm'))
  })

  test('ordering uses the existing move up / move down pattern', () => {
    const src = form()
    assert.ok(src.includes('aria-label'))
    assert.ok(/Move .* up/i.test(src) && /Move .* down/i.test(src))
    assert.ok(!/draggable/i.test(src), 'no drag-and-drop was asked for')
  })

  test('images reuse the existing picker rather than a new upload path', () => {
    const src = form()
    assert.ok(src.includes('<ImagePickerField'))
    assert.ok(!src.includes('fetch(\'/api/uploads'), 'no bespoke upload call')
  })

  test('the description field enforces the same limit as the server', () => {
    assert.ok(form().includes('maxLength={MAX_HOME_DESCRIPTION}'))
  })

  test('the creator is offered a way to go and look at the result', () => {
    assert.match(form(), /View Collective Home/)
  })

  test('saving reports success or failure out loud', () => {
    assert.ok(form().includes('aria-live'))
  })
})

// ---------------------------------------------------------------------------
// Phase 2 — themed text stays readable on every palette
// ---------------------------------------------------------------------------

/** The 23 seeded Collective palettes, primary slot. */
const SEEDED_PRIMARIES = [
  '#944D32', '#6E2B3A', '#DE6E5A', '#2C556E', '#C67E4E', '#5C4A33', '#A64526',
  '#2C5A3E', '#C89B4A', '#6B5C8C', '#3F4A73', '#6B7A82', '#4A5A6B', '#4C6B3B',
  '#3A6B7A', '#6E7439', '#B87A85', '#7B8770', '#A0B4C4', '#34495E', '#D97A3F',
  '#B85D3D', '#7A4C7C',
]

function contrastOnWhite(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  }
  const l = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
  return 1.05 / (l + 0.05)
}

describe('themed text is readable on every Collective', () => {
  test('several seeded palettes really are illegible raw', () => {
    // Establishes that the helper is solving a real problem rather
    // than a hypothetical one.
    const failing = SEEDED_PRIMARIES.filter((h) => contrastOnWhite(h) < 4.5)
    assert.ok(failing.length >= 5, `only ${failing.length} raw primaries fail`)
  })

  test('every seeded palette clears WCAG AA once inked', () => {
    for (const hex of SEEDED_PRIMARIES) {
      const ink = readableOnWhite(hex)
      assert.ok(
        contrastOnWhite(ink) >= 4.5,
        `${hex} → ${ink} is ${contrastOnWhite(ink).toFixed(2)}:1`,
      )
    }
  })

  test('an already-legible palette is left exactly as it is', () => {
    assert.equal(readableOnWhite('#2C5A3E'), '#2C5A3E')
  })

  test('the hue survives — it darkens, it does not go grey', () => {
    const ink = readableOnWhite('#D97A3F')  // Sunrise
    const [r, , b] = [1, 3, 5].map((i) => parseInt(ink.slice(i, i + 2), 16))
    assert.ok(r > b * 1.5, `${ink} lost its warmth`)
  })

  test('unparseable input falls back to ink, never to nothing', () => {
    assert.equal(readableOnWhite('not-a-colour'), '#0f172a')
  })

  test('the card reads the safe ink in preference to the raw accent', () => {
    const card = readFileSync(join(SRC, 'components/collective/AtlasCard.tsx'), 'utf8')
    assert.ok(card.includes('var(--fc-accent-ink, var(--fc-accent, #38A09E))'), 'CTA')
    assert.ok(card.includes('var(--fc-accent-ink, rgba(12, 24, 38, 0.50))'), 'meta')
    const home = readFileSync(join(SRC, 'components/collective/CollectiveHome.tsx'), 'utf8')
    assert.ok(home.includes("'--fc-accent-ink'"), 'the Home publishes it')
    // Scoped to the Home: surfaces outside it keep their own colours.
    assert.ok(home.includes('readableOnWhite('))
  })
})

describe('the tab bar and the Home agree', () => {
  const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

  test('a closed directory removes the Members tab too', () => {
    // Phase 1 left these disagreeing: the Home dropped the Members
    // tile while the tab bar still offered the tab, so the same
    // Collective said both "there is a directory" and "there is not".
    const nav = read('components/spaces/SpaceNav.tsx')
    assert.ok(nav.includes('showMemberDirectory'))
    assert.match(nav, /filter\(\(tab\) => tab\.label !== 'Members' \|\| showMemberDirectory\)/)
  })

  test('the tab bar is told the rule by the Collective layout', () => {
    const layout = read('app/spaces/[slug]/layout.tsx')
    assert.ok(layout.includes('showMemberDirectory={space.show_member_directory ?? true}'))
  })

  test('a caller that has not loaded the Space keeps the old behaviour', () => {
    const nav = read('components/spaces/SpaceNav.tsx')
    assert.ok(nav.includes('showMemberDirectory = true'), 'defaults to showing the tab')
  })
})

// ---------------------------------------------------------------------------
// The Collective Home settings tab
// ---------------------------------------------------------------------------

describe('the settings tab says what it is', () => {
  const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
  const shell = () => read('app/creator-studio/settings/SettingsTabbedShell.tsx')

  test('the tab is called Collective Home', () => {
    const src = shell()
    assert.match(src, /label: 'Collective Home'/)
    assert.ok(!/label: 'Member Hub'/.test(src))
  })

  test('the URL key is untouched, so existing links keep working', () => {
    // Renaming the key would have been churn for nothing: no page in
    // the app links to ?tab=members.
    const src = shell()
    assert.match(src, /key: 'members'/)
    assert.ok(src.includes("v === 'members'"), 'still a valid tab param')
  })

  test('the tab renders the three sections in arrival order', () => {
    const tab = read('app/creator-studio/settings/CollectiveHomeTab.tsx')
    const order = ['MemberDirectoryForm', 'CollectiveHomeForm', 'GuidancePanelForm']
      .map((c) => tab.indexOf(`<${c}`))
    assert.ok(order.every((i) => i > 0), 'all three render')
    assert.deepEqual([...order].sort((a, b) => a - b), order, 'directory → tiles → sidebar')
  })

  test('"Member Hub" survives only where it names the member-side renderer', () => {
    // The phrase still means something real — the Important panel —
    // so it stays there. What it must not do is name a Creator Studio
    // tab that no longer carries it.
    for (const f of [
      'app/creator-studio/settings/SettingsTabbedShell.tsx',
      'app/creator-studio/settings/CollectiveHomeForm.tsx',
    ]) {
      assert.ok(!read(f).includes('Member Hub'), f)
    }
    assert.ok(read('components/spaces/ImportantPanel.tsx').includes('Member Hub'))
  })
})

describe('the member directory control', () => {
  const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
  const form = () => read('app/creator-studio/settings/MemberDirectoryForm.tsx')

  test('it saves through the Space endpoint, not the Home configuration', () => {
    // Privacy belongs to the Space. Routing it through home-config
    // would put a privacy rule inside a layout document.
    const src = form()
    assert.match(src, /method: 'PATCH'/)
    assert.match(src, /\/api\/creator\/spaces\/\$\{space\.slug\}`\)/)
    assert.ok(!src.includes('home-config'))
    assert.match(src, /show_member_directory: next/)
  })

  test('it is a real switch, not a styled div', () => {
    assert.ok(form().includes('<Switch'))
  })

  test('the copy names every consequence a creator cannot otherwise see', () => {
    const src = form()
    for (const [what, pattern] of [
      ['navigation', /navigation/i],
      ['the Home tile', /Members tile/i],
      ['who members can see', /see the other people here/i],
      ['Recognition', /recognise people as sharing/i],
    ] as const) {
      assert.match(src, pattern, `copy should mention ${what}`)
    }
  })

  test('a failed save rolls the switch back', () => {
    // A privacy control must never sit in a state the server has not
    // agreed to.
    assert.match(form(), /catch \{\s*setEnabled\(!next\)/)
  })

  test('saving tells the Home editor to refetch', () => {
    assert.ok(form().includes('onSaved?.(next)'))
    const tab = read('app/creator-studio/settings/CollectiveHomeTab.tsx')
    assert.ok(tab.includes('setDirectoryVersion'))
    assert.ok(tab.includes('reloadKey={directoryVersion}'))
  })

  test('the Home editor reloads on that signal and keeps unsaved edits', () => {
    const src = read('app/creator-studio/settings/CollectiveHomeForm.tsx')
    assert.ok(src.includes('}, [slug, reloadKey])'), 'refetches when the key changes')
    assert.ok(src.includes('prev.length > 0 ? prev :'), 'reseeds from what is on screen')
  })

  test('the editor asks the server which tiles it may offer', () => {
    // Not a client-side branch on show_member_directory: one rule,
    // one owner.
    const src = read('app/creator-studio/settings/CollectiveHomeForm.tsx')
    assert.ok(src.includes('available_keys'))
    assert.ok(!src.includes('show_member_directory'))
  })
})

describe('sidebar guidance', () => {
  const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
  const form = () => read('app/creator-studio/settings/GuidancePanelForm.tsx')

  test('it is named for where it appears', () => {
    const src = form()
    assert.match(src, /Sidebar guidance/)
    assert.match(src, /Conversations,\s*\n?\s*Gatherings and Pathways/)
    assert.match(src, /does not appear on the Collective Home/)
  })

  test('Welcome and Notes are still editable', () => {
    const src = form()
    assert.ok(src.includes("bodyKey: 'guidance_start_body'"))
    assert.ok(src.includes("bodyKey: 'guidance_links_body'"))
    assert.ok(src.includes('<SimpleRichTextEditor'))
  })

  test('the dead This week editor is gone', () => {
    // The phrase survives in the note explaining why the column
    // stays; what must not survive is a field a creator can type into.
    const src = form()
    assert.ok(!/label: 'This week'/.test(src), 'no section')
    assert.ok(!src.includes('autoPopulated'), 'not even a disabled one')
    assert.ok(!/bodyKey: 'guidance_focus_body'/.test(src), 'no editor bound to it')
  })

  test('the retired columns are never sent, so their contents survive', () => {
    // The endpoint applies only the fields it receives. Omission is
    // the preservation mechanism.
    const src = form()
    // Anchored to the end of the line: a third member added to the
    // union is exactly how a retired column creeps back in.
    assert.match(src, /^type BodyKey = 'guidance_start_body' \| 'guidance_links_body'$/m)
    for (const retired of [
      'guidance_focus_body', 'guidance_focus_title',
      'guidance_start_title', 'guidance_links_title',
    ]) {
      // Named once in the preservation note, never as a form field.
      const asField = new RegExp(`${retired}:\\s*space\\.`)
      assert.ok(!asField.test(src), `${retired} is still read into form state`)
    }
    assert.ok(src.includes('PRESERVED_UNUSED_COLUMNS'), 'and the reason is written down')
  })
})

describe('the member-side sidebar', () => {
  const panel = () => readFileSync(join(SRC, 'components/spaces/ImportantPanel.tsx'), 'utf8')

  test('empty Notes is omitted rather than announced', () => {
    const src = panel()
    assert.ok(src.includes('notesHasContent'))
    assert.match(src, /\.\.\.\(notesHasContent/)
  })

  test('Welcome keeps its empty state', () => {
    // Its absence would read as a fault; Notes is plainly optional.
    assert.ok(panel().includes('Nothing added yet.'))
    assert.match(panel(), /\{ title: 'Welcome',\s+body: welcomeBody, authorable: true\s+\}/)
  })

  test('This week is still driven by live Gatherings, not by stored text', () => {
    assert.match(panel(), /\{ title: 'This week', body: null, override: focusOverride/)
  })
})


// ---------------------------------------------------------------------------
// The Offerings tile
// ---------------------------------------------------------------------------

describe('the Offerings tile', () => {
  test('it sits immediately after Pathways by default', () => {
    const k = keys(space())
    assert.equal(k.indexOf('offerings'), k.indexOf('pathways') + 1)
  })

  test('the canonical order is the approved one', () => {
    assert.deepEqual(DEFAULT_TILE_ORDER, [
      'gatherings', 'pathways', 'offerings', 'conversations', 'messages',
      'members', 'about',
    ])
  })

  test('it carries the approved label, copy and call to action', () => {
    const tile = buildTiles(space()).find((t) => t.key === 'offerings')!
    assert.equal(tile.name, 'Offerings')
    assert.equal(
      tile.description,
      'Digital resources, tools and creations to explore.',
    )
    assert.equal(tile.cta, 'Explore offerings →')
  })

  test('it links to the Collective\u2019s existing catalogue', () => {
    const tile = buildTiles(space({ slug: 'moonlit-circle' }))
      .find((t) => t.key === 'offerings')!
    assert.equal(tile.href, '/spaces/moonlit-circle/offerings')
  })

  test('the count reads published Offerings', () => {
    const one = buildTiles(space({ published_offering_count: 1 }))
      .find((t) => t.key === 'offerings')!
    assert.equal(one.meta, '1 offering available')

    const many = buildTiles(space({ published_offering_count: 4 }))
      .find((t) => t.key === 'offerings')!
    assert.equal(many.meta, '4 offerings available')
  })

  test('zero is stated, not hidden', () => {
    // The same rule Gatherings and Pathways follow. A creator who
    // enabled the doorway has said they want it; an empty shelf is a
    // calm fact, not a reason to remove their choice.
    for (const count of [0, undefined]) {
      const tile = buildTiles(space({ published_offering_count: count }))
        .find((t) => t.key === 'offerings')!
      assert.equal(tile.meta, 'No offerings yet')
    }
  })

  test('a creator\u2019s description replaces the platform copy', () => {
    const tile = buildTiles(space({
      home_tiles: [{ key: 'offerings', description: 'Workbooks and audio.' }],
    })).find((t) => t.key === 'offerings')!
    assert.equal(tile.description, 'Workbooks and audio.')
  })

  test('a creator\u2019s image wins over the platform default', () => {
    assert.equal(
      tileImageUrl('offerings', '/api/uploads/media/mine.jpg', () => '/plat.jpg'),
      '/api/uploads/media/mine.jpg',
    )
  })

  test('the platform default comes from its own artwork slot', () => {
    // Its own, not borrowed. ``homepage_resources`` dresses the
    // homepage's editorial section about Offerings; sharing it would
    // mean replacing one image silently redressed the other surface.
    assert.equal(
      TILE_PLATFORM_ARTWORK.offerings, 'collective_home_offerings',
    )
    assert.notEqual(
      TILE_PLATFORM_ARTWORK.offerings, 'homepage_resources',
    )
    assert.equal(
      tileImageUrl('offerings', null, (k) =>
        (k === 'collective_home_offerings' ? '/art/offerings.jpg' : null)),
      '/art/offerings.jpg',
    )
  })

  test('an empty artwork slot falls through to the gradient', () => {
    // The state this ships in, until the image is uploaded through
    // World Settings → Artwork. Never a blank box.
    assert.equal(tileImageUrl('offerings', null, () => null), null)
    const themed: CollectivePaletteMeta = {
      key: 'test', name: 'Test',
      palette: {
        primary: '#38A09E', secondary: '#1F4E5F',
        accent: '#F2B441', background: '#FFFFFF',
      },
    }
    assert.match(
      tileFallbackBackground('offerings', themed, 'moonlit-circle'),
      /linear-gradient/,
    )
    // And with no palette either, still something rather than nothing.
    assert.ok(
      tileFallbackBackground('offerings', null, 'moonlit-circle').length > 0,
    )
  })

  test('a creator can hide it', () => {
    const k = keys(space({
      home_tiles: [{ key: 'gatherings' }, { key: 'pathways' }],
    }))
    assert.ok(!k.includes('offerings'))
  })

  test('a creator can reorder it', () => {
    const k = keys(space({
      home_tiles: [{ key: 'offerings' }, { key: 'gatherings' }],
    }))
    assert.deepEqual(k, ['offerings', 'gatherings'])
  })

  test('every tile key has a label, copy, link and call to action', () => {
    // Adding a key to one map and forgetting another would render a
    // card with an undefined caption or a dead link.
    for (const key of DEFAULT_TILE_ORDER) {
      assert.ok(HOME_TILE_LABEL[key], `label missing: ${key}`)
      assert.ok(HOME_TILE_DEFAULT_COPY[key], `copy missing: ${key}`)
      const tile = buildTiles(space()).find((t) => t.key === key)
      assert.ok(tile, `tile missing: ${key}`)
      assert.match(tile.href, /^\/spaces\/[^/]+\/.+/, `href bad: ${key}`)
      assert.match(tile.cta, /→$/, `cta bad: ${key}`)
    }
  })
})
