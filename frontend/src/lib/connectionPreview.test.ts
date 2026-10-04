import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  MAX_PREVIEW_CARDS,
  PREVIEW_PEOPLE,
  PREVIEW_SETS,
  previewSet,
  previewConversation,
  previewPersonRef,
  previewThreadSummaries,
  resolvePreviewImage,
} from './connectionPreviewFixtures.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const PAGE = 'app/dev/connection-preview/page.tsx'
const FIXTURES = 'lib/connectionPreviewFixtures.ts'
const CARD = 'components/connections/PersonCard.tsx'
const CONVO = 'app/messages/[threadId]/PeerConversationClient.tsx'

/** Real uploaded artwork, as the live payload provides it. Every
 *  letter the fixtures and the tests reach for, plus two photographic
 *  assets standing in for member photos. */
const ARTWORK = new Map<string, string | null>([
  ['member_card_a', '/api/uploads/platform-artwork/member_card_a/A.webp'],
  ['member_card_d', '/api/uploads/platform-artwork/member_card_d/D.webp'],
  ['member_card_j', '/api/uploads/platform-artwork/member_card_j/J.webp'],
  ['member_card_m', '/api/uploads/platform-artwork/member_card_m/M.webp'],
  ['member_card_r', '/api/uploads/platform-artwork/member_card_r/R.webp'],
  ['member_card_t', '/api/uploads/platform-artwork/member_card_t/T.webp'],
  ['member_card_w', '/api/uploads/platform-artwork/member_card_w/W.webp'],
  ['member_card_z', '/api/uploads/platform-artwork/member_card_z/Z.webp'],
  ['member_card_neutral', '/api/uploads/platform-artwork/member_card_neutral/N.webp'],
  ['homepage_conversations', '/api/uploads/platform-artwork/homepage_conversations/c.webp'],
  ['homepage_ways_to_connect', '/api/uploads/platform-artwork/homepage_ways_to_connect/w.webp'],
])

describe('access is Platform Owner only', () => {
  const src = codeOnly(PAGE)

  test('it uses the canonical owner check', () => {
    assert.match(src, /await viewerIsPlatformOwner\(\)/)
    assert.match(src, /notFound\(\)/)
  })

  test('the check is awaited, not treated as a boolean', () => {
    // `if (!viewerIsPlatformOwner())` would be falsy-negated on a
    // Promise and open the harness to everybody.
    assert.match(src, /if \(!\(await viewerIsPlatformOwner\(\)\)\) notFound\(\)/)
  })

  test('access does not depend on the URL being obscure', () => {
    for (const smell of ['searchParams.secret', 'token', 'NODE_ENV']) {
      assert.ok(!src.includes(smell), `access must not hinge on ${smell}`)
    }
  })

  test('it is never prerendered', () => {
    assert.match(src, /export const dynamic = 'force-dynamic'/)
  })

  test('it is excluded from search', () => {
    assert.match(src, /robots: \{ index: false, follow: false \}/)
  })
})

describe('nothing is written and nothing is posted', () => {
  test('every interactive component is in preview mode', () => {
    const src = codeOnly(PAGE)
    // ``[^<]*`` and not ``[\s\S]*?``: a lazy any-character match will
    // happily run past the end of this element and satisfy itself on
    // the *next* component's prop, so dropping one of the two would
    // slip through.
    assert.match(src, /<PeopleYouveCrossed[^<]*previewOnly/)
    assert.match(src, /<PeerConversationClient[^<]*previewOnly/)
  })

  test('the harness itself makes no mutating calls', () => {
    const src = codeOnly(PAGE)
    for (const verb of ["method: 'POST'", "method: 'DELETE'", 'sayHello(', 'blockPeer(', 'reportPeer(']) {
      assert.ok(!src.includes(verb), `the harness must not ${verb}`)
    }
  })

  test('the card suppresses both of its network paths in preview mode', () => {
    const src = codeOnly(CARD)
    // Two separate paths — opening a conversation and sending a hello.
    // Asserting the guard *once* would pass while the other leaked, so
    // each is pinned to its own function body.
    const openBody = src.match(/async function openMessage\(\)[\s\S]*?\n  \}/)?.[0]
    const sendBody = src.match(/async function send\(\)[\s\S]*?\n  \}/)?.[0]
    assert.ok(openBody, 'openMessage not found')
    assert.ok(sendBody, 'send not found')
    assert.match(openBody, /if \(previewOnly\) \{/)
    assert.match(sendBody, /if \(previewOnly\) \{/)
    // In preview, opening a conversation is a route change, not a fetch.
    assert.match(openBody, /router\.push\(previewMessageHref\)/)
    // The real calls are still there for production.
    assert.match(sendBody, /await sayHello\(person\.id\)/)
  })

  test('the conversation suppresses send, block, unblock and report', () => {
    const src = codeOnly(CONVO)
    assert.match(src, /if \(previewOnly\) \{[\s\S]*?setDraft\(''\)/)
    assert.match(src, /if \(!previewOnly\) await blockPeer/)
    assert.match(src, /if \(!previewOnly\) await unblockPeer/)
    assert.match(src, /previewOnly\s*\?\s*'FC-PREVIEW'/)
  })

  test('preview mode defaults off, so production is unaffected', () => {
    for (const path of [CARD, CONVO, 'components/connections/PeopleYouveCrossed.tsx']) {
      assert.match(codeOnly(path), /previewOnly = false/)
    }
  })
})

describe('the harness renders the real components', () => {
  test('no second visual implementation', () => {
    const src = codeOnly(PAGE)
    for (const real of [
      'PeopleYouveCrossed', 'WaysToConnectEmptyState', 'PeerThreadList',
      'PeerConversationClient', 'SiteShell', 'PageHero',
    ]) {
      assert.ok(src.includes(real), `must reuse ${real}`)
    }
  })

  test('it does not hand-roll a card or a message bubble', () => {
    const src = codeOnly(PAGE)
    assert.ok(!/<MemberImage/.test(src), 'cards own their own imagery')
    assert.ok(!/message\.body/.test(src))
  })

  test('both Ways to Connect states are selectable', () => {
    const src = codeOnly(PAGE)
    assert.match(src, /WTC_STATES = \['populated', 'empty'\]/)
  })

  test('all three conversation states are selectable', () => {
    const src = codeOnly(PAGE)
    assert.match(src, /CONVO_STATES: ConversationState\[\] = \['normal', 'blocked', 'report'\]/)
  })

  test('it is labelled as a prototype', () => {
    assert.match(read(PAGE), /Internal prototype — no data is saved/)
  })

  test('no preview-specific CSS could mask a responsive problem', () => {
    const src = codeOnly(PAGE)
    // No *fixed* width, no transform scaling. ``max-w-`` is allowed and
    // expected: it is the real page's own responsive container, copied
    // so the harness frames content exactly as production does.
    assert.ok(
      !/(^|[^-])w-\[\d{3,}px\]/.test(src),
      'a fixed width would hide a responsive problem',
    )
    assert.ok(!/scale-\d/.test(src))
    assert.ok(!/zoom/.test(src))
  })
})

describe('the fixtures cover every relationship state', () => {
  test('all four states appear', () => {
    const states = new Set(PREVIEW_PEOPLE.map((p) => p.relationship))
    for (const expected of ['none', 'outgoing', 'incoming', 'mutual']) {
      assert.ok(states.has(expected as never), `missing state: ${expected}`)
    }
  })

  test('there are two mutual connections, to judge repetition', () => {
    assert.equal(
      PREVIEW_PEOPLE.filter((p) => p.relationship === 'mutual').length, 2,
    )
  })

  test('the hello set leads with the incoming hello', () => {
    assert.equal(previewSet('hello').people[0].relationship, 'incoming')
  })

  test('the cast is never rendered as one list', () => {
    // The harness renders a *set*. The cast exists to be drawn from.
    assert.ok(!codeOnly(PAGE).includes('PREVIEW_PEOPLE'))
  })

  test('photo, alphabet card and neutral are all represented', () => {
    const kinds = new Set(PREVIEW_PEOPLE.map((p) => p.image.kind))
    assert.ok(kinds.has('photo'))
    assert.ok(kinds.has('alphabet'))
    assert.ok(kinds.has('neutral'))
  })
})

describe('the fixtures respect 5a eligibility semantics', () => {
  test('everybody has at least two signals', () => {
    for (const p of PREVIEW_PEOPLE) {
      assert.ok(p.shared.length >= 2, `${p.name} has fewer than two signals`)
    }
  })

  test('everybody has at least one realised signal', () => {
    for (const p of PREVIEW_PEOPLE) {
      const realised = p.shared.filter(
        (s) => s.kind === 'pathway' || (s.kind === 'gathering' && s.basis === 'attended'),
      )
      assert.ok(
        realised.length >= 1,
        `${p.name} is justified only by upcoming Gatherings`,
      )
    }
  })

  test('nobody is justified by two upcoming Gatherings', () => {
    for (const p of PREVIEW_PEOPLE) {
      const upcoming = p.shared.filter(
        (s) => s.kind === 'gathering' && s.basis === 'upcoming',
      )
      assert.ok(upcoming.length <= 1, `${p.name} leans on plans alone`)
    }
  })

  test('Collective membership is never presented as the reason', () => {
    const src = read(FIXTURES)
    assert.ok(
      !/basis: 'collective'/.test(src),
      'membership is the boundary, never a signal',
    )
    for (const p of PREVIEW_PEOPLE) {
      for (const s of p.shared) {
        assert.ok(['gathering', 'pathway'].includes(s.kind))
      }
    }
  })

  test('no contact information anywhere in the fixtures', () => {
    // Comment-stripped: the module's own docstring says the words
    // "phone" and "address" in the course of promising they are absent,
    // and a raw check would fail on the promise rather than a breach.
    const src = codeOnly(FIXTURES)
    assert.ok(
      !/['"`][^'"`\s]+@[^'"`\s]+\.[a-z]{2,}['"`]/i.test(src),
      'no email addresses',
    )
    for (const word of ['phone', 'address', 'mobile', '+61']) {
      assert.ok(!src.toLowerCase().includes(word), `no ${word}`)
    }
  })

  test('ids are obviously synthetic', () => {
    for (const p of PREVIEW_PEOPLE) {
      assert.match(p.id, /^prev-/)
    }
  })
})

describe('images resolve through the real member-image payload', () => {
  test('a photo wins', () => {
    const img = resolvePreviewImage(
      { kind: 'photo', artworkKey: 'homepage_conversations', initial: 'A', fallbackLetter: 'A' },
      ARTWORK,
    )
    assert.equal(img.kind, 'photo')
    assert.equal(img.url, ARTWORK.get('homepage_conversations'))
  })

  test('a photo is served from an origin the production CSP allows', () => {
    // The first version of these fixtures used images.unsplash.com.
    // Production's img-src is 'self', the API origin, R2 and data: —
    // so both photos were blocked and the two people carrying them
    // were the two that looked broken under review.
    const src = codeOnly(FIXTURES)
    assert.ok(!/https?:\/\//.test(src), 'no external image hosts')
    for (const person of PREVIEW_PEOPLE) {
      if (person.image.kind !== 'photo') continue
      const url = resolvePreviewImage(person.image, ARTWORK).url ?? ''
      assert.ok(
        url.startsWith('/'),
        `${person.name}'s photo is not same-origin: ${url}`,
      )
    }
  })

  test('a photo carries the card it degrades to', () => {
    const img = resolvePreviewImage(
      { kind: 'photo', artworkKey: 'homepage_conversations', initial: 'A', fallbackLetter: 'A' },
      ARTWORK,
    )
    assert.equal(img.fallback_url, ARTWORK.get('member_card_a'))
  })

  test('a photo that cannot load still ends on a card, not a glyph', () => {
    const img = resolvePreviewImage(
      { kind: 'broken-photo', initial: 'W', fallbackLetter: 'W' }, ARTWORK,
    )
    assert.equal(img.kind, 'photo')
    assert.ok(img.fallback_url, 'there has to be something below it')
    assert.equal(img.fallback_url, ARTWORK.get('member_card_w'))
  })

  test('a photo falls to neutral when its letter has no card', () => {
    const img = resolvePreviewImage(
      { kind: 'photo', artworkKey: 'homepage_conversations', initial: 'Q', fallbackLetter: 'Q' },
      ARTWORK,
    )
    assert.equal(img.fallback_url, ARTWORK.get('member_card_neutral'))
  })

  test('an alphabet card uses the real uploaded artwork', () => {
    const img = resolvePreviewImage({ kind: 'alphabet', letter: 'M' }, ARTWORK)
    assert.equal(img.kind, 'alphabet')
    assert.equal(img.url, ARTWORK.get('member_card_m'))
    assert.equal(img.initial, 'M')
  })

  test('every letter resolves, not just the first one anybody checked', () => {
    // A and J were the two reported as broken. They were photos, not
    // monograms — but a per-letter check is what rules the key
    // derivation in or out, so it is worth having.
    for (const letter of ['A', 'D', 'J', 'M', 'R', 'T', 'W', 'Z']) {
      const img = resolvePreviewImage({ kind: 'alphabet', letter }, ARTWORK)
      assert.equal(img.kind, 'alphabet', `letter ${letter}`)
      assert.equal(img.url, ARTWORK.get(`member_card_${letter.toLowerCase()}`))
    }
  })

  test('the lookup key is lowercase whatever case the letter arrives in', () => {
    assert.equal(
      resolvePreviewImage({ kind: 'alphabet', letter: 'j' }, ARTWORK).url,
      resolvePreviewImage({ kind: 'alphabet', letter: 'J' }, ARTWORK).url,
    )
  })

  test('a missing card falls back to the plain initial, as the real resolver does', () => {
    const img = resolvePreviewImage({ kind: 'alphabet', letter: 'Q' }, ARTWORK)
    assert.equal(img.kind, 'initial')
    assert.equal(img.url, null)
    assert.equal(img.initial, 'Q')
  })

  test('a name with no usable A–Z letter gets the neutral card', () => {
    const img = resolvePreviewImage({ kind: 'neutral' }, ARTWORK)
    assert.equal(img.kind, 'neutral')
    assert.equal(img.url, ARTWORK.get('member_card_neutral'))
  })

  test('person refs carry a valid MemberImage', () => {
    for (const p of PREVIEW_PEOPLE) {
      const ref = previewPersonRef(p, ARTWORK)
      assert.ok(['photo', 'alphabet', 'neutral', 'initial'].includes(ref.image.kind))
      assert.equal(ref.display_name, p.name)
    }
  })
})

describe('the inbox and conversation fixtures', () => {
  test('four conversations with varied states', () => {
    const threads = previewThreadSummaries(ARTWORK)
    assert.equal(threads.length, 4)
    assert.ok(threads.some((t) => t.unread_count > 0), 'one unread')
    assert.ok(threads.some((t) => t.unread_count === 0), 'and some read')
  })

  test('previews are short and have timestamps', () => {
    for (const t of previewThreadSummaries(ARTWORK)) {
      assert.ok((t.last_message ?? '').length < 80)
      assert.ok(t.last_message_at)
    }
  })

  test('the conversation alternates and is 8–12 messages', () => {
    const convo = previewConversation(ARTWORK)
    assert.ok(convo.messages.length >= 8 && convo.messages.length <= 12)
    const senders = new Set(convo.messages.map((m) => m.sender_user_id))
    assert.equal(senders.size, 2, 'both sides speak')
  })

  test('the normal state can send', () => {
    const convo = previewConversation(ARTWORK, 'normal')
    assert.equal(convo.can_send, true)
    assert.equal(convo.blocked_by_me, false)
  })

  test('the blocked state has no composer and keeps its history', () => {
    const convo = previewConversation(ARTWORK, 'blocked')
    assert.equal(convo.can_send, false)
    assert.equal(convo.blocked_by_me, true)
    assert.ok(convo.messages.length > 0, 'history survives a block')
  })

  test('fixtures are stable across loads', () => {
    // Not Date.now(): a preview that shifts under review is harder to
    // judge than one that does not.
    assert.deepEqual(
      previewConversation(ARTWORK).messages.map((m) => m.created_at),
      previewConversation(ARTWORK).messages.map((m) => m.created_at),
    )
  })
})


describe('the prototype never shows more people than the product', () => {
  test('no fixture set holds more than three', () => {
    for (const set of PREVIEW_SETS) {
      assert.ok(
        set.people.length <= MAX_PREVIEW_CARDS,
        `set '${set.key}' holds ${set.people.length}`,
      )
    }
  })

  test('the page slices as well as trusts the data', () => {
    // A fixture set growing to four should not be able to produce a
    // four-card page, which is what the first version of the prototype
    // did with seven.
    assert.match(codeOnly(PAGE), /\.slice\(0, MAX_PREVIEW_CARDS\)/)
  })

  test('the limit mirrors the product rather than inventing one', () => {
    assert.equal(MAX_PREVIEW_CARDS, 3)
    assert.match(
      read(FIXTURES),
      /selection\.MAX_PEOPLE/,
      'the fixture limit should name the backend authority it mirrors',
    )
  })

  test('there are three sets, and they cover every state', () => {
    assert.equal(PREVIEW_SETS.length, 3)
    assert.deepEqual(
      PREVIEW_SETS.map((s) => s.key), ['discovery', 'hello', 'connected'],
    )
    const covered = new Set(
      PREVIEW_SETS.flatMap((s) => s.people.map((p) => p.relationship)),
    )
    for (const state of ['none', 'outgoing', 'incoming', 'mutual']) {
      assert.ok(covered.has(state as never), `no set shows '${state}'`)
    }
  })

  test('every image tier is reviewable across the sets', () => {
    const kinds = new Set(
      PREVIEW_SETS.flatMap((s) => s.people.map((p) => p.image.kind)),
    )
    for (const kind of ['photo', 'broken-photo', 'alphabet', 'neutral']) {
      assert.ok(kinds.has(kind as never), `no set shows a '${kind}' image`)
    }
  })

  test('the connected set shows two mutuals, to judge repetition', () => {
    const mutual = previewSet('connected').people
      .filter((p) => p.relationship === 'mutual')
    assert.equal(mutual.length, 2)
  })

  test('an unknown or absent set falls back rather than erroring', () => {
    assert.equal(previewSet(undefined).key, 'discovery')
    assert.equal(previewSet('nonsense').key, 'discovery')
  })

  test('the set control exists only in the prototype', () => {
    for (const path of [
      'app/ways-to-connect/page.tsx',
      'components/connections/PeopleYouveCrossed.tsx',
      'components/connections/PersonCard.tsx',
    ]) {
      const src = codeOnly(path)
      assert.ok(!src.includes('PREVIEW_SETS'), `${path} knows about fixtures`)
      assert.ok(!src.includes('previewSet'), `${path} knows about fixtures`)
    }
  })

  test('the real page adds no pagination or directory behaviour', () => {
    const src = codeOnly('app/ways-to-connect/page.tsx')
    for (const smell of ['View all', 'view all', 'Show more', 'page=', 'offset']) {
      assert.ok(!src.includes(smell), `directory behaviour crept in: ${smell}`)
    }
  })
})
