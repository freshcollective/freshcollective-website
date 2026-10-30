import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { unseenForCollective } from './unseenForCollective.ts'
import type { UnseenCountsResponse } from '@/types/platform'

/**
 * What the Collective Home badges its tiles with.
 *
 * The Home reads ``unseen-counts`` once and keys the result by tile.
 * Pathways, Gatherings and Conversations carried numbers; Messages
 * did not — not because the count was unavailable but because it used
 * to need a second request. It now rides on the same response, so the
 * Messages tile badges from data the page already has.
 *
 * The number is the member's own unread private messages, which for a
 * creator means replies from their members. It is never folded into
 * the activity numbers beside it.
 */

const row = (over: Partial<UnseenCountsResponse['collectives'][number]> = {}) => ({
  collective_id: 'sp_1',
  conversations: 0,
  pathways: 0,
  gatherings: 0,
  total: 0,
  conversation_channels: [],
  ...over,
})

const response = (
  collectives: UnseenCountsResponse['collectives'],
): UnseenCountsResponse => ({
  collectives,
  total: collectives.reduce((n, c) => n + c.total, 0),
  as_of_sequence: 1,
})


describe('the Messages tile gets its number', () => {
  test('an unread count reaches the messages key', () => {
    const out = unseenForCollective(
      response([row({ unread_messages: 3 })]), 'sp_1',
    )
    assert.equal(out?.messages, 3)
  })

  test('no unread messages is zero, which renders no badge', () => {
    // ``CountBadge`` returns null below 1 — zero is absence, not a
    // state to draw.
    const out = unseenForCollective(response([row({ unread_messages: 0 })]), 'sp_1')
    assert.equal(out?.messages, 0)
  })

  test('an older API response without the field degrades to zero', () => {
    // fc-api and fc-web deploy from one push but not in one instant.
    const out = unseenForCollective(response([row()]), 'sp_1')
    assert.equal(out?.messages, 0)
  })

  test('the tile key matches the one the Home renders', () => {
    const tiles = readFileSync('src/lib/collectiveHomeTiles.ts', 'utf8')
    assert.match(tiles, /messages: 'Messages'/)
    const out = unseenForCollective(response([row({ unread_messages: 1 })]), 'sp_1')
    assert.ok(out && 'messages' in out)
  })
})


describe('it stays separate from the activity numbers', () => {
  test('messages are not added to any activity category', () => {
    const out = unseenForCollective(
      response([row({
        conversations: 1, pathways: 2, gatherings: 3, total: 6,
        unread_messages: 5,
      })]),
      'sp_1',
    )
    assert.deepEqual(out, {
      conversations: 1, pathways: 2, gatherings: 3, messages: 5,
    })
  })

  test('messages alone leave every activity count at zero', () => {
    const out = unseenForCollective(
      response([row({ unread_messages: 4 })]), 'sp_1',
    )
    assert.deepEqual(out, {
      conversations: 0, pathways: 0, gatherings: 0, messages: 4,
    })
  })
})


describe('it reads the right Collective', () => {
  test('each Collective gets its own count', () => {
    const res = response([
      row({ collective_id: 'sp_1', unread_messages: 2 }),
      row({ collective_id: 'sp_2', unread_messages: 7 }),
    ])
    assert.equal(unseenForCollective(res, 'sp_1')?.messages, 2)
    assert.equal(unseenForCollective(res, 'sp_2')?.messages, 7)
  })

  test('a Collective absent from the response badges nothing at all', () => {
    // ``undefined`` rather than zeros: the Home renders no badges
    // instead of asserting there is nothing unseen.
    assert.equal(unseenForCollective(response([row()]), 'sp_missing'), undefined)
  })
})
