/**
 * Channel dots — one per Channel, never a number.
 *
 * Notifications 2.0 put a count on Conversations that can only be
 * cleared one Channel at a time, into a selector whose stated design
 * rule was "no badges, no counts, no dots". The dot resolves that: it
 * says which Channel to open without turning navigation into a tally.
 *
 * Two things here are easy to break without noticing — a count
 * creeping into the selector, and the dots quietly costing a second
 * request. Both are asserted below.
 *
 * Source-contract tests: the project has no DOM renderer (node:test,
 * no jsdom), so components are pinned by reading their source.
 * Comments are stripped with the quote-aware walker used elsewhere —
 * the naive regex treats `accept="image/*"` as a comment opener.
 */

import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

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
const raw = (p: string) => readFileSync(p, 'utf8')

const SELECTOR_PATH = 'src/components/community/ChannelSelector.tsx'
const SELECTOR = read(SELECTOR_PATH)
const PAGE = read('src/app/spaces/[slug]/community/page.tsx')
const NAV = read('src/components/spaces/SpaceNav.tsx')

// ---------------------------------------------------------------------------
// 1 · A dot, and only a dot
// ---------------------------------------------------------------------------

describe('the channel dot', () => {
  test('a Channel with unseen activity gets one', () => {
    assert.match(SELECTOR, /unseen\.has\(c\.id\) && \(/)
    assert.match(SELECTOR, /rounded-full/)
    assert.match(SELECTOR, /h-\[6px\] w-\[6px\]/)
  })

  test('nothing unseen renders nothing', () => {
    // Gated on set membership, so an empty set produces no element at
    // all — never a hollow or zero dot.
    assert.match(SELECTOR, /const unseen = new Set\(unseenChannelIds \?\? \[\]\)/)
  })

  test('the selector never renders a count', () => {
    for (const banned of [/CountBadge/, /conversations\b.*\d/, /\{count\}/]) {
      assert.ok(
        !banned.test(SELECTOR),
        `${banned} — the number belongs to the navigation badge, not here`,
      )
    }
  })

  test('it receives ids, not counts, so a number cannot leak in', () => {
    assert.match(SELECTOR, /unseenChannelIds\?: readonly string\[\]/)
  })

  test('the dot is spoken, not shown, to assistive technology', () => {
    assert.match(SELECTOR, /aria-hidden="true"[\s\S]{0,200}h-\[6px\]/)
    assert.match(SELECTOR, /sr-only">\{`unseen activity in \$\{c\.name\}`\}/)
  })

  test('it reads on the active pill as well as the inactive one', () => {
    // The active pill is a filled teal lozenge with white text; an
    // accent-coloured dot would vanish into it.
    assert.match(SELECTOR, /active \? '#FFFFFF' : 'var\(--fc-accent/)
  })
})

// ---------------------------------------------------------------------------
// 2 · The design rule it replaces
// ---------------------------------------------------------------------------

describe('the stated design rule', () => {
  test('the old no-dots rule is gone, not contradicted', () => {
    // Read raw: this rule lives in the header comment, which
    // ``codeOnly`` strips.
    const header = raw(SELECTOR_PATH)
    assert.ok(
      !/- No unread badges, no counts, no dots\./.test(header),
      'the component still claims it renders no dots while rendering one',
    )
    assert.match(header, /One dot, and only a dot/)
  })
})

// ---------------------------------------------------------------------------
// 3 · The dots cost no extra request
// ---------------------------------------------------------------------------

describe('where the dots come from', () => {
  test('the page reuses the counts response it already fetched', () => {
    assert.equal((PAGE.match(/getUnseenCounts\(/g) ?? []).length, 1)
    assert.match(PAGE, /const counts = await getUnseenCounts\(\)/)
    assert.match(PAGE, /conversation_channels/)
  })

  test('the boundary still comes from that same response', () => {
    // Stage B's contract: the boundary is captured before the content.
    // Reusing the response must not have moved it.
    const boundary = PAGE.indexOf('getUnseenCounts(')
    const content = PAGE.indexOf('getCommunityFeed(')
    assert.ok(boundary !== -1 && content !== -1 && boundary < content)
    assert.match(PAGE, /const boundary = counts\.as_of_sequence/)
  })

  test('the page passes the ids to the selector', () => {
    assert.match(PAGE, /unseenChannelIds=\{unseenChannelIds\}/)
  })
})

// ---------------------------------------------------------------------------
// 4 · The navigation badge is untouched
// ---------------------------------------------------------------------------

describe('the main Conversations badge', () => {
  test('the nav still renders numbers through the shared badge', () => {
    assert.match(NAV, /import CountBadge/)
    assert.match(NAV, /unseenByCategory\[area\] \?\? 0/)
  })

  test('the nav grew no dots', () => {
    assert.ok(
      !/h-\[6px\] w-\[6px\]/.test(NAV),
      'dots belong to the channel selector; the nav keeps its count',
    )
  })
})
