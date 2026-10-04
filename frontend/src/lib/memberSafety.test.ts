import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { REPORT_CATEGORIES } from './peerMessages.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const CLIENT = 'app/messages/[threadId]/PeerConversationClient.tsx'
const LIB = 'lib/peerMessages.ts'

describe('the composer closes when a block stands', () => {
  const src = codeOnly(CLIENT)

  test('sending is gated on the server’s can_send, not on local state', () => {
    assert.match(src, /!thread\.can_send \? \(/)
  })

  test('the blocker is told plainly and offered the way back', () => {
    assert.match(src, /You&rsquo;ve blocked \{name\}/)
    assert.match(src, /Unblock \$\{name\}/)
  })

  test('the blocked person is never told who closed it', () => {
    // The branch keys on blocked_by_me, which is false for them.
    assert.match(src, /thread\.blocked_by_me \? \(/)
    const closedBranch = src.slice(
      src.indexOf('!thread.can_send ? ('),
      src.indexOf('<form onSubmit={submit}'),
    )
    assert.ok(
      !/blocked you|has blocked|they blocked/i.test(closedBranch),
      'a boundary must not become a confrontation',
    )
  })

  test('history stays visible either way', () => {
    assert.match(src, /history is still here|conversation is still here/i)
  })

  test('unblocking re-reads rather than assuming', () => {
    // If the other person has also blocked, the conversation stays
    // closed and only the server knows.
    const fn = src.slice(src.indexOf('async function doUnblock'))
    assert.match(fn.slice(0, 400), /await reload\(\)/)
  })
})

describe('the safety controls are quiet', () => {
  const src = codeOnly(CLIENT)

  test('they sit behind one unobtrusive control', () => {
    assert.match(src, /setSafetyOpen\(\(open\) => !open\)/)
    assert.match(src, /Safety options for this conversation/)
  })

  test('block asks for confirmation and explains the consequences', () => {
    assert.match(src, /Block \{name\}\?/)
    assert.match(src, /won&rsquo;t be able to message each other/)
    assert.match(src, /appear to each other in Ways to Connect/)
    assert.match(src, /existing conversation will remain/)
    assert.match(src, /won&rsquo;t be told/)
  })

  test('the language is calm, not punitive', () => {
    for (const word of [
      'ban', 'banned', 'offender', 'violation', 'abuse report',
      'permanently', 'punish',
    ]) {
      assert.ok(
        !new RegExp(word, 'i').test(src),
        `avoid punitive language: ${word}`,
      )
    }
  })

  test('reporting is never contingent on blocking', () => {
    assert.match(src, /Reporting doesn&rsquo;t block/)
    // The block offer after a report is an invitation, not a coupling.
    assert.match(src, /Would you also like to block \{name\}\?/)
    const reportFn = src.slice(src.indexOf('async function doReport'))
    assert.ok(
      !/blockPeer/.test(reportFn.slice(0, 600)),
      'submitting a report must not block anyone',
    )
  })

  test('the acknowledgement names the case reference', () => {
    assert.match(src, /Thank you for telling us/)
    assert.match(src, /\{caseNumber\}/)
  })
})

describe('the safety transport', () => {
  const src = codeOnly(LIB)

  test('block, unblock and report hit the peer endpoints', () => {
    assert.match(src, /\/block`, \{\s*method: 'POST'/)
    assert.match(src, /\/block`, \{\s*method: 'DELETE'/)
    assert.match(src, /\/report`/)
  })

  test('thread ids are encoded', () => {
    const safety = src.slice(src.indexOf('export async function blockPeer'))
    assert.ok((safety.match(/encodeURIComponent\(threadId\)/g) ?? []).length >= 3)
  })

  test('no blocked user id is ever sent — the thread identifies them', () => {
    const safety = src.slice(src.indexOf('export async function blockPeer'))
    assert.ok(!/user_id/.test(safety))
  })

  test('failures throw so the UI can retry', () => {
    const safety = src.slice(src.indexOf('export async function blockPeer'))
    assert.ok((safety.match(/if \(!res\.ok\) throw/g) ?? []).length >= 3)
  })
})

describe('report categories', () => {
  test('they mirror the backend list', () => {
    const values = REPORT_CATEGORIES.map((c) => c.value)
    for (const expected of [
      'harassment_or_bullying', 'hate_or_discrimination', 'spam_or_scam',
      'unsafe_behaviour', 'misinformation', 'inappropriate_content',
      'privacy_information', 'something_else',
    ]) {
      assert.ok(values.includes(expected), `missing category: ${expected}`)
    }
  })

  test('every category has human-readable copy', () => {
    for (const c of REPORT_CATEGORIES) {
      assert.ok(c.label.length > 0)
      assert.ok(!c.label.includes('_'), `raw enum leaked into the UI: ${c.label}`)
    }
  })

  test('something_else requires a note in the form', () => {
    const src = codeOnly(CLIENT)
    assert.match(src, /required=\{reportCategory === 'something_else'\}/)
  })
})

describe('no internal identifiers reach the member', () => {
  test('the conversation never renders a raw id', () => {
    const src = codeOnly(CLIENT)
    assert.ok(!/\{thread\.thread_id\}/.test(src), 'thread ids are not UI')
    assert.ok(!/\{thread\.other\.id\}/.test(src))
    assert.ok(!/sender_user_id\}/.test(src))
  })
})
