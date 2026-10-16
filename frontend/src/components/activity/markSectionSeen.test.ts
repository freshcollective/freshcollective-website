/**
 * Phase 3, Stage B — reporting what was presented.
 *
 * Only activity genuinely presented to the member may be marked
 * seen. Two things enforce that on the client side, and both are
 * easy to break without noticing:
 *
 *  1. the page sends the ids it rendered — never a sequence, never
 *     a sentinel;
 *  2. the page captures its boundary **before** fetching content.
 *
 * (2) is the one that rots quietly. Moving the boundary into the
 * same `Promise.all` as the content would look tidier, pass every
 * behavioural test, and silently start clearing steps published
 * mid-request. There is a test below that fails if the lines are
 * reordered.
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

const MARKER = read('src/components/activity/MarkSectionSeen.tsx')

const SECTIONS = {
  conversations: {
    file: 'src/app/spaces/[slug]/community/page.tsx',
    content: 'getCommunityFeed(',
  },
  pathways: {
    file: 'src/app/spaces/[slug]/pathways/page.tsx',
    content: 'getSpacePathways(',
  },
  gatherings: {
    file: 'src/app/spaces/[slug]/events/page.tsx',
    content: 'getSpaceEvents(',
  },
} as const

// ---------------------------------------------------------------------------
// 1 · The boundary is captured before the content
// ---------------------------------------------------------------------------

describe('the render-time boundary', () => {
  for (const [name, { file, content }] of Object.entries(SECTIONS)) {
    test(`${name}: the boundary is awaited before the content fetch`, () => {
      const src = read(file)
      const boundary = src.indexOf('getUnseenCounts(')
      const first = src.indexOf(content)
      assert.notEqual(boundary, -1, 'no boundary captured')
      assert.notEqual(first, -1, `no ${content} call found`)
      assert.ok(
        boundary < first,
        'the boundary must be captured BEFORE the content is fetched — ' +
          'taken afterwards it includes activity created in between, ' +
          'which was never rendered and would be cleared anyway',
      )
    })

    test(`${name}: the boundary is awaited, not raced`, () => {
      const src = read(file)
      // `await getUnseenCounts()` on its own line, not inside the
      // Promise.all that fetches content.
      assert.match(
        src,
        /const boundary = \(await getUnseenCounts\(\)\)\.as_of_sequence/,
        'the boundary must be its own await, not a member of Promise.all',
      )
    })

    test(`${name}: a marker is mounted with that boundary`, () => {
      const src = read(file)
      assert.match(src, /<MarkSectionSeen/)
      assert.match(src, /boundarySequence=\{boundary\}/)
      assert.match(src, new RegExp(`category="${name}"`))
    })

    test(`${name}: the marker is mounted only when the Collective loaded`, () => {
      const src = read(file)
      // ``requireArea`` does NOT stop a null space: a Collective that
      // failed to load has no ``area_access``, and ``canReachArea``
      // reads an absent policy as "open". So the id must be reached
      // through a guard, never a non-null assertion — otherwise the
      // page throws mid-render instead of the layout's clean 404.
      assert.ok(
        !/space!/.test(src),
        'space is nullable here — guard the marker, do not assert',
      )
      assert.match(src, /\{space && \(\s*<MarkSectionSeen/)
    })
  }
})

// ---------------------------------------------------------------------------
// 2 · The client never names a sequence
// ---------------------------------------------------------------------------

describe('what the client is allowed to assert', () => {
  test('the marker sends subject ids and the boundary, and nothing else', () => {
    assert.match(MARKER, /subject_ids: subjectIds/)
    assert.match(MARKER, /boundary_sequence: boundarySequence/)
  })

  test('it never computes or sends a sequence of its own', () => {
    for (const banned of [/through_sequence/, /Math\.max/, /sequence_number/]) {
      assert.ok(
        !banned.test(MARKER),
        `${banned} — the client must not decide what was seen`,
      )
    }
  })

  test('an empty list posts nothing', () => {
    assert.match(MARKER, /subjectIds\.length === 0[\s\S]{0,40}return/)
  })

  test('a zero boundary posts nothing', () => {
    assert.match(MARKER, /boundarySequence <= 0[\s\S]{0,40}return/)
  })

  test('a failed report is swallowed and never retried', () => {
    assert.match(MARKER, /\} catch \{/)
    assert.ok(!/retry|setTimeout|setInterval/.test(MARKER))
  })

  test('it refreshes only when something actually advanced', () => {
    assert.match(MARKER, /Object\.keys\(body\.advanced[\s\S]{0,40}router\.refresh\(\)/)
  })
})

