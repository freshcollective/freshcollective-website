import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  PREVIEW_PEOPLE,
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

/** Real uploaded artwork, as the live payload provides it. */
const ARTWORK = new Map<string, string | null>([
  ['member_card_m', '/uploads/member-card-m.png'],
  ['member_card_neutral', '/uploads/member-card-neutral.png'],
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

  test('an incoming hello is first, as the real page orders it', () => {
    assert.equal(PREVIEW_PEOPLE[0].relationship, 'incoming')
  })

  test('there are five to seven people', () => {
    assert.ok(PREVIEW_PEOPLE.length >= 5 && PREVIEW_PEOPLE.length <= 7)
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
      { kind: 'photo', url: '/p.jpg', initial: 'A' }, ARTWORK,
    )
    assert.equal(img.kind, 'photo')
    assert.equal(img.url, '/p.jpg')
  })

  test('an alphabet card uses the real uploaded artwork', () => {
    const img = resolvePreviewImage({ kind: 'alphabet', letter: 'M' }, ARTWORK)
    assert.equal(img.kind, 'alphabet')
    assert.equal(img.url, '/uploads/member-card-m.png')
    assert.equal(img.initial, 'M')
  })

  test('a missing card falls back to the plain initial, as the real resolver does', () => {
    const img = resolvePreviewImage({ kind: 'alphabet', letter: 'Z' }, ARTWORK)
    assert.equal(img.kind, 'initial')
    assert.equal(img.url, null)
    assert.equal(img.initial, 'Z')
  })

  test('a name with no usable A–Z letter gets the neutral card', () => {
    const img = resolvePreviewImage({ kind: 'neutral' }, ARTWORK)
    assert.equal(img.kind, 'neutral')
    assert.equal(img.url, '/uploads/member-card-neutral.png')
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
