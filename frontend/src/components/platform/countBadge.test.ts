/**
 * Phase 3, Stage A — the badges.
 *
 * What a number may say, where it may appear, and what it must
 * never say. Stage A ships these without the seen-state reporting
 * that clears them — see markSectionSeen.test.ts for that half.
 *
 * No DOM renderer here (node:test, no jsdom), so components are
 * pinned by reading the source. Comments are stripped with the
 * quote-aware walker used elsewhere — the naive regex treats
 * `accept="image/*"` as a comment opener.
 */

import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import { unseenForCollective } from '../../lib/unseenForCollective.ts'

function codeOnly(src: string): string {
  let out = ''
  let i = 0
  let quote: string | null = null
  while (i < src.length) {
    const c = src[i]
    const next = src[i + 1]
    if (quote) {
      out += c
      if (c === '\\') { out += next ?? ''; i += 2; continue }
      if (c === quote) quote = null
      i += 1
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; out += c; i += 1; continue }
    if (c === '/' && next === '*') {
      const end = src.indexOf('*/', i + 2)
      i = end === -1 ? src.length : end + 2
      continue
    }
    if (c === '/' && next === '/') {
      const end = src.indexOf('\n', i)
      i = end === -1 ? src.length : end
      continue
    }
    out += c
    i += 1
  }
  return out
}

const read = (p: string) => codeOnly(readFileSync(p, 'utf8'))

const BADGE = read('src/components/platform/CountBadge.tsx')
const NAV = read('src/components/spaces/SpaceNav.tsx')
const BELL = read('src/components/layout/NotificationBell.tsx')
const DASH = read('src/app/dashboard/page.tsx')
const HOME = read('src/components/collective/CollectiveHome.tsx')
const HOME_PAGE = read('src/app/spaces/[slug]/page.tsx')
const LAYOUT = read('src/app/spaces/[slug]/layout.tsx')

// ---------------------------------------------------------------------------
// 3 · The badge
// ---------------------------------------------------------------------------

describe('CountBadge', () => {
  test('zero renders nothing at all', () => {
    assert.match(BADGE, /if \(!count \|\| count < 1\) return null/)
  })

  test('the cap is 9+, and there is only one of them', () => {
    // Anchored: /const CAP = 9/ also matches `99`, which is the
    // bell's ceiling and the wrong answer here.
    assert.match(BADGE, /const CAP = 9\b(?!\d)/)
    assert.match(BADGE, /count > CAP \? `\$\{CAP\}\+`/)
    assert.equal((BADGE.match(/CAP = /g) ?? []).length, 1)
  })

  test('the number is hidden from assistive tech and a sentence given', () => {
    assert.match(BADGE, /aria-hidden="true">\{shown\}/)
    assert.match(BADGE, /sr-only">\{`\$\{count\} new \$\{label\}`\}/)
  })

  test('the corner variant exists and is positioned', () => {
    assert.match(BADGE, /variant === 'corner'/)
    assert.match(BADGE, /absolute -right-1\.5 -top-1/)
  })
})

// ---------------------------------------------------------------------------
// 4 · Where badges may and may not appear
// ---------------------------------------------------------------------------

describe('placement', () => {
  test('the nav uses the shared badge, with no inline copies left', () => {
    assert.match(NAV, /import CountBadge/)
    assert.ok(
      !/unreadMessageCount > 9 \?/.test(NAV),
      'an inline badge survived — that is how the 9 / 9+ drift happened',
    )
  })

  test('only the three member categories can carry one', () => {
    assert.match(NAV, /const unseenFor = \(label: string\)/)
    assert.match(NAV, /AREA_FOR_TAB\[label\]/)
    // Members and About are in AREA_FOR_TAB but have no activity
    // category, so they resolve to undefined and render nothing.
    assert.match(NAV, /unseenByCategory\[area\] \?\? 0/)
  })

  test('Messages keeps its own count, separate from activity', () => {
    assert.match(NAV, /count=\{unreadMessageCount\} label="in Messages"/)
  })

  test('the bell keeps its own 99+ ceiling', () => {
    assert.match(BELL, /unreadCount > 99 \? '99\+'/)
    assert.ok(!/CountBadge/.test(BELL), 'the bell was not in scope')
  })

  test('Your World puts the combined total at the card corner', () => {
    assert.match(DASH, /absolute right-3 top-3/)
    assert.match(DASH, /<CountBadge variant="card" count=\{unseen\}/)
  })

  test('Your World fetches every Collective in one request', () => {
    assert.match(DASH, /const unseenCounts = await getUnseenCounts\(\)/)
    assert.equal((DASH.match(/getUnseenCounts\(/g) ?? []).length, 1)
  })
})

// ---------------------------------------------------------------------------
// 5 · The card variant — a badge laid over artwork
// ---------------------------------------------------------------------------

describe('the card variant', () => {
  test('it is about 22px with a larger numeral', () => {
    assert.match(BADGE, /variant === 'card'/)
    assert.match(BADGE, /h-\[22px\] min-w-\[22px\] px-\[5px\] text-\[12px\]/)
  })

  test('it carries a white keyline and a shadow', () => {
    // Without the keyline a teal disc vanishes into a teal-green
    // headland, which is the whole reason this variant exists.
    assert.match(BADGE, /boxShadow: '0 0 0 2px #fff/)
  })

  test('the keyline is scoped to this variant alone', () => {
    assert.match(BADGE, /\.\.\.\(variant === 'card'\s*\?\s*\{ boxShadow/)
  })

  test('the navigation variants are untouched', () => {
    assert.match(BADGE, /absolute -right-1\.5 -top-1 h-3\.5 min-w-\[14px\] px-\[3px\] text-\[8px\]/)
    assert.match(BADGE, /h-4 min-w-\[16px\] px-\[3px\] text-\[9px\]/)
  })

  test('it inherits the cap, the colour and the spoken sentence', () => {
    // Nothing variant-specific may sit near any of these. A badge on
    // artwork may look different; it may not say anything different.
    assert.equal((BADGE.match(/CAP = /g) ?? []).length, 1)
    assert.equal((BADGE.match(/aria-hidden="true"/g) ?? []).length, 1)
    assert.equal((BADGE.match(/sr-only/g) ?? []).length, 1)
    assert.equal((BADGE.match(/--fc-accent, #38A09E/g) ?? []).length, 1)
    assert.equal((BADGE.match(/return null/g) ?? []).length, 1)
  })
})

// ---------------------------------------------------------------------------
// 6 · Where the card variant is used
// ---------------------------------------------------------------------------

describe('Your World and Collective Home', () => {
  test('the Home tiles use the shared badge, not a local one', () => {
    assert.match(HOME, /import CountBadge/)
    assert.match(HOME, /variant="card"/)
    assert.match(HOME, /absolute right-3 top-3/)
    // An absolutely positioned badge needs a positioned ancestor —
    // the tile itself, or it pins to the page instead.
    assert.match(HOME, /className="group relative block h-full/)
  })

  test('a tile with no category resolves to nothing, with no allow-list', () => {
    // Members and About are real tile keys with nothing behind them.
    // They must fall out by resolving to no count, not by being
    // listed — which is also how Messages joined without touching
    // this lookup: it simply gained a key in the projection.
    assert.match(HOME, /unseenByCategory\?\.\[tile\.key\] \?\? 0/)
    assert.match(HOME, /\{unseen > 0 && \(/)
  })

  test('the Home invents no counting logic of its own', () => {
    for (const banned of [/collectives\.find/, /\.reduce\(/, /conversations:/]) {
      assert.ok(
        !banned.test(HOME),
        `${banned} — the Home renders counts, it does not derive them`,
      )
    }
  })

  test('the Home costs no extra request', () => {
    // One unscoped call, cache()-deduped with the layout's. A scoped
    // call would be a second cache key and a second round trip.
    assert.equal((HOME_PAGE.match(/getUnseenCounts\(/g) ?? []).length, 1)
    assert.match(HOME_PAGE, /await getUnseenCounts\(\)/)
  })

  test('the layout and the Home share one projection', () => {
    assert.match(LAYOUT, /unseenForCollective\(await getUnseenCounts\(\), space\.id\)/)
    assert.match(HOME_PAGE, /unseenForCollective\(/)
  })

  test('opening the Home advances no cursor', () => {
    // The Home reads counts. Clearing a section is the business of
    // visiting that section — see markSectionSeen.test.ts.
    for (const src of [HOME, HOME_PAGE]) {
      assert.ok(!/MarkSectionSeen/.test(src), 'the Home must mount no marker')
      assert.ok(!/activities\/seen/.test(src), 'the Home must not report seen state')
    }
  })
})

// ---------------------------------------------------------------------------
// 7 · The projection itself
// ---------------------------------------------------------------------------

describe('unseenForCollective', () => {
  const counts = {
    collectives: [
      { collective_id: 'a', conversations: 3, pathways: 0, gatherings: 2, total: 5 },
      { collective_id: 'b', conversations: 0, pathways: 1, gatherings: 0, total: 1 },
    ],
    total: 6,
    as_of_sequence: 42,
  }

  test('it picks the named Collective, not the first row', () => {
    assert.deepEqual(unseenForCollective(counts, 'b'), {
      conversations: 0, pathways: 1, gatherings: 0, messages: 0,
    })
  })

  test('a Collective with no row is unknown, not clear', () => {
    // undefined renders no badges. A zeroed map would be a claim that
    // every section has been read.
    assert.equal(unseenForCollective(counts, 'missing'), undefined)
    assert.equal(unseenForCollective({ collectives: [], total: 0, as_of_sequence: 0 }, 'a'), undefined)
  })

  test('it carries the badge-able keys and no total', () => {
    // Was three. ``messages`` joined them when the unread count
    // started riding on this response — the Messages tile badges from
    // the same request rather than needing one of its own. ``total``
    // still never appears: the tiles badge per category, and the
    // message count is not part of the activity sum.
    const projected = unseenForCollective(counts, 'a')
    assert.deepEqual(
      Object.keys(projected ?? {}).sort(),
      ['conversations', 'gatherings', 'messages', 'pathways'],
    )
    assert.ok(!('total' in (projected ?? {})))
  })
})
