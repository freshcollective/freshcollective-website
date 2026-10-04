import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { participantName } from './peerMessages.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const CARD = 'components/connections/PersonCard.tsx'
const LIB = 'lib/peerMessages.ts'
const INBOX = 'app/messages/page.tsx'
const THREAD = 'app/messages/[threadId]/page.tsx'
const CLIENT = 'app/messages/[threadId]/PeerConversationClient.tsx'
const HEADER = 'components/layout/WorldHeader.tsx'

describe('Message appears only on a mutual connection', () => {
  const src = codeOnly(CARD)

  test('the Message action sits inside the mutual branch', () => {
    const mutualStart = src.indexOf('isMutual ? (')
    const nextBranch = src.indexOf('isOutgoing || state ===')
    const mutualBranch = src.slice(mutualStart, nextBranch)
    assert.match(mutualBranch, /Message →/)
    assert.match(mutualBranch, /openMessage/)
  })

  test('no other state offers Message', () => {
    const mutualStart = src.indexOf('isMutual ? (')
    const nextBranch = src.indexOf('isOutgoing || state ===')
    const everythingElse =
      src.slice(0, mutualStart) + src.slice(nextBranch)
    assert.ok(
      !/Message →/.test(everythingElse),
      'Message must not appear in none / outgoing / incoming',
    )
  })

  test('opening a conversation does not send anything', () => {
    assert.ok(!/sendPeerMessage/.test(src))
    assert.match(src, /openConversation\(person\.id\)/)
  })

  test('the other states are unchanged', () => {
    assert.match(src, /Connected/)
    assert.match(src, /Hello sent/)
    assert.match(src, /Say hello back/)
    assert.match(src, /'Say hello back' : 'Say hello'/)
  })
})

describe('the conversation renders plain text', () => {
  const src = codeOnly(CLIENT)

  test('no HTML injection surface', () => {
    assert.ok(
      !/dangerouslySetInnerHTML/.test(src),
      'a member-authored body must never be rendered as markup',
    )
  })

  test('the body is rendered as a text node', () => {
    assert.match(src, /\{message\.body\}/)
  })

  test('it re-reads from the server after sending', () => {
    // The server sanitises, so what is stored can differ from what was
    // typed; the thread should show what the other person will see.
    assert.match(src, /setThread\(await fetchPeerThread/)
  })

  test('own and received messages are distinguished by sender id', () => {
    assert.match(src, /sender_user_id === currentUserId/)
  })

  test('an empty draft cannot be sent', () => {
    assert.match(src, /draft\.trim\(\)\.length === 0/)
  })

  test('no chat-product extras crept in', () => {
    for (const word of [
      'typing', 'reaction', 'attachment', 'emoji picker',
      'online', 'seen at', 'read receipt',
    ]) {
      assert.ok(
        !new RegExp(word, 'i').test(src),
        `out of scope for v1: ${word}`,
      )
    }
  })
})

describe('the inbox is the peer surface, not the creator one', () => {
  test('it lists peer threads', () => {
    const src = codeOnly(INBOX)
    assert.match(src, /getPeerThreads/)
  })

  test('it never reaches a Collective-scoped message route', () => {
    const src = codeOnly(INBOX) + codeOnly(THREAD) + codeOnly(CLIENT) + codeOnly(LIB)
    assert.ok(
      !/\/api\/spaces\/[^"'`]*\/messages/.test(src),
      'the creator↔member surface is left alone',
    )
    assert.ok(!/creator_id|creator inbox/i.test(src))
  })

  test('both pages are gated on Ways to Connect availability', () => {
    for (const page of [INBOX, THREAD]) {
      const src = codeOnly(page)
      // The shared gate: the launch flag, plus the Platform Owner
      // preview. Awaited, because a bare Promise would be truthy and
      // open the page to everybody.
      assert.match(src, /await waysToConnectVisible\(\)/)
      assert.match(src, /notFound\(\)/)
    }
  })

  test('a thread that is not mine is indistinguishable from one that does not exist', () => {
    const src = codeOnly(THREAD)
    assert.match(src, /if \(!thread \|\| !me\?\.id\) notFound\(\)/)
  })

  test('profile pictures come from the shared resolver', () => {
    for (const page of [INBOX, CLIENT]) {
      const src = codeOnly(page)
      assert.match(src, /<MemberImage image=/)
    }
    // No second monogram implementation.
    const both = codeOnly(INBOX) + codeOnly(CLIENT)
    assert.ok(!/charAt\(0\)/.test(both))
    assert.ok(!/toUpperCase\(\)/.test(both))
  })

  test('the inbox is never prerendered', () => {
    // Without force-dynamic, Next builds this page while the flag is
    // false, bakes in the notFound() result, and keeps serving that 404
    // after the flag is turned on. Caught in the build output as "○
    // /messages" rather than "ƒ".
    assert.match(codeOnly(INBOX), /export const dynamic = 'force-dynamic'/)
  })

  test('Messages rides the Ways to Connect flag, not a new one', () => {
    const src = codeOnly(HEADER)
    assert.match(src, /if \(waysToConnectOn\) items\.push\(\{ href: '\/messages'/)
  })
})

describe('the transport', () => {
  const src = codeOnly(LIB)

  test('it posts to the peer endpoints', () => {
    assert.match(src, /\/api\/messages\/\$\{encodeURIComponent\(threadId\)\}\/messages/)
    // Opening lives beside the other Ways to Connect calls, because it
    // is reached from a person card rather than from the inbox.
    assert.match(codeOnly('lib/waysToConnect.ts'), /'\/api\/messages\/open'/)
  })

  test('ids are encoded into paths', () => {
    assert.ok((src.match(/encodeURIComponent/g) ?? []).length >= 2)
  })

  test('a non-2xx throws so the UI can offer a retry', () => {
    assert.ok((src.match(/if \(!res\.ok\) throw/g) ?? []).length >= 2)
  })

  test('no sender is ever put in a request body', () => {
    // ``sender_user_id`` is legitimately a field on the *response*
    // type, so the assertion has to be about what we serialise.
    const bodies = src.match(/JSON\.stringify\(\{[^}]*\}\)/g) ?? []
    assert.ok(bodies.length > 0, 'expected at least one request body')
    for (const body of bodies) {
      assert.ok(
        !/sender/.test(body),
        `the server takes the sender from auth: ${body}`,
      )
    }
  })
})

describe('participantName', () => {
  test('uses the display name when there is one', () => {
    assert.equal(
      participantName({ id: 'u1', display_name: 'Sarah', image: { kind: 'initial', url: null, initial: 'S' } }),
      'Sarah',
    )
  })

  test('falls back rather than rendering an empty heading', () => {
    for (const name of [null, '', '   ']) {
      assert.equal(
        participantName({ id: 'u1', display_name: name, image: { kind: 'initial', url: null, initial: null } }),
        'A member',
      )
    }
  })
})
