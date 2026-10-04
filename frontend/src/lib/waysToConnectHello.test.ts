import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/**
 * The card documents the states it deliberately does *not* offer —
 * notably a Message action — so a raw substring check would trip on the
 * explanation rather than a regression.
 */
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const CARD = 'components/connections/PersonCard.tsx'
const LIB = 'lib/waysToConnect.ts'
const IMAGE = 'components/ui/MemberImage.tsx'

describe('the card renders server-owned relationship state', () => {
  test('state is seeded from the payload, not from a click', () => {
    const src = codeOnly(CARD)
    assert.match(src, /person\.relationship \?\? 'none'/)
  })

  test('all four states are handled', () => {
    const src = codeOnly(CARD)
    assert.match(src, /relationship === 'mutual'/)
    assert.match(src, /relationship === 'incoming'/)
    assert.match(src, /relationship === 'outgoing'/)
  })

  test('an optimistic send never outranks the server on re-render', () => {
    // `sentNow` only *adds* outgoing; it cannot override mutual.
    const src = codeOnly(CARD)
    assert.match(src, /sentNow && !isMutual/)
  })
})

describe('each state says the right thing', () => {
  const src = codeOnly(CARD)

  test('mutual reads as Connected and stops asking', () => {
    assert.match(src, /Connected/)
    const mutualBranch = src.slice(src.indexOf('isMutual ? ('), src.indexOf('isOutgoing'))
    assert.ok(
      !/Say hello/.test(mutualBranch),
      'a connected card must not keep offering to say hello',
    )
  })

  test('outgoing reads as pending and is not a button', () => {
    const outgoing = src.slice(src.indexOf("Hello sent"), src.indexOf("Hello sent") + 400)
    assert.ok(
      !/<button/.test(outgoing),
      'there is nothing useful to do with a second click',
    )
  })

  test('incoming names the person and offers to reply', () => {
    assert.match(src, /said hello/)
    assert.match(src, /Say hello back/)
  })

  test('the default state offers a plain hello', () => {
    assert.match(src, /'Say hello back' : 'Say hello'/)
  })

  test('no social-network language anywhere', () => {
    for (const word of [
      'friend request', 'connection request', 'networking',
      'connect with', 'add friend', 'follow',
    ]) {
      assert.ok(
        !new RegExp(word, 'i').test(src),
        `this is Fresh Collective, not LinkedIn: found "${word}"`,
      )
    }
  })

  test('no Message action is offered', () => {
    // The existing messaging model is creator-to-member inside a
    // Collective and has no peer thread, so a Message button would be
    // a promise the backend cannot keep.
    assert.ok(!/>\s*Message\s*</.test(src))
    assert.ok(!/\/messages/.test(src))
  })
})

describe('the hello client is honest about failure', () => {
  test('it posts to the canonical endpoint', () => {
    const src = codeOnly(LIB)
    assert.match(src, /\/api\/ways-to-connect\/\$\{encodeURIComponent\(personId\)\}\/hello/)
    assert.match(src, /method: 'POST'/)
  })

  test('a non-2xx throws so the card can offer a retry', () => {
    const src = codeOnly(LIB)
    assert.match(src, /if \(!res\.ok\) throw/)
  })

  test('the user id is encoded into the path', () => {
    const src = codeOnly(LIB)
    assert.match(src, /encodeURIComponent\(personId\)/)
  })

  test('the relationship type mirrors the backend states', () => {
    const src = codeOnly(LIB)
    assert.match(
      src,
      /HelloRelationship = 'none' \| 'outgoing' \| 'incoming' \| 'mutual'/,
    )
  })
})

describe('the person card keeps its 288px treatment', () => {
  test('full width on a phone, fixed from md up', () => {
    const src = codeOnly(CARD)
    assert.match(src, /w-full flex-col/)
    assert.match(src, /md:w-\[288px\]/)
  })
})

describe('profile images come from the shared resolver', () => {
  test('the card renders the backend-resolved image', () => {
    const src = codeOnly(CARD)
    assert.match(src, /<MemberImage image=\{person\.image\}/)
  })

  test('the card invents no monogram of its own', () => {
    const src = codeOnly(CARD)
    // No CSS initials, no letter slicing — the resolver decided.
    assert.ok(!/charAt\(0\)/.test(src))
    assert.ok(!/\.slice\(0, 1\)/.test(src))
    assert.ok(!/toUpperCase\(\)/.test(src))
  })

  test('the shared component handles photo, alphabet card and initial', () => {
    const src = codeOnly(IMAGE)
    assert.match(src, /kind === 'photo'/)
    assert.match(src, /image\.initial/)
  })
})
