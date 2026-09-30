/**
 * The Connect-routing attention line.
 *
 * The rules under test are all "when does this appear and when does it go
 * away", because the item is derived rather than stored — there is no
 * dedup key or resolve step to test, only the condition.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import
import { connectRoutingItems } from './adminAttention.ts'

describe('connectRoutingItems', () => {
  test('a ready creator gets a line naming them, linking to their page', () => {
    const items = connectRoutingItems([{ user_id: 'usr_7', name: 'Ada Lovelace' }])
    assert.equal(items.length, 1)
    assert.equal(items[0].label, 'Ada Lovelace is ready for Stripe Connect routing.')
    assert.equal(items[0].href, '/admin/creators/usr_7')
  })

  test('one line per creator, not a count — the link is the useful part', () => {
    const items = connectRoutingItems([
      { user_id: 'usr_1', name: 'One' },
      { user_id: 'usr_2', name: 'Two' },
      { user_id: 'usr_3', name: 'Three' },
    ])
    assert.equal(items.length, 3)
    assert.deepEqual(items.map((i) => i.href), [
      '/admin/creators/usr_1',
      '/admin/creators/usr_2',
      '/admin/creators/usr_3',
    ])
  })

  test('nobody ready means no line at all', () => {
    // The backend drops a creator from this list the moment routing is
    // enabled or readiness lapses, so an empty list is how the item clears.
    assert.deepEqual(connectRoutingItems([]), [])
  })

  test('an older backend that does not send the field is not an error', () => {
    assert.deepEqual(connectRoutingItems(undefined), [])
  })

  test('routine, not critical — nothing is broken and no money is stuck', () => {
    const items = connectRoutingItems([{ user_id: 'usr_1', name: 'One' }])
    assert.equal(items[0].severity, 'routine')
  })

  test('the name is taken verbatim, so an email fallback reads correctly', () => {
    // users.name is nullable; the backend substitutes the email.
    const items = connectRoutingItems([
      { user_id: 'usr_9', name: 'nameless@example.com' },
    ])
    assert.equal(
      items[0].label,
      'nameless@example.com is ready for Stripe Connect routing.',
    )
  })
})
