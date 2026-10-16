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

  test('both variants exist and the corner one is positioned', () => {
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
    assert.match(DASH, /<CountBadge count=\{unseen\}/)
  })

  test('Your World fetches every Collective in one request', () => {
    assert.match(DASH, /const unseenCounts = await getUnseenCounts\(\)/)
    assert.equal((DASH.match(/getUnseenCounts\(/g) ?? []).length, 1)
  })
})
