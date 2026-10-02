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


// ---------------------------------------------------------------------------
// Money Fresh Collective is owed back
// ---------------------------------------------------------------------------

// @ts-expect-error - Node-native import
import { connectRecoveryItems } from './adminAttention.ts'

const owed = (overrides: Record<string, unknown> = {}) => ({
  creator_user_id: 'usr_1',
  creator_name: 'Ada Lovelace',
  currency: 'AUD',
  outstanding_cents: 151,
  transaction_count: 1,
  sample_transaction_id: 'txn_abc',
  ...overrides,
})

describe('connectRecoveryItems', () => {
  test('names the creator, the amount, and who is owed', () => {
    const [item] = connectRecoveryItems([owed()])
    assert.match(item.label, /Ada Lovelace/)
    assert.match(item.label, /\$1\.51/)
    assert.match(item.label, /owes Fresh Collective/)
  })

  test('says the member was refunded, so nobody reads it as a failed refund', () => {
    // The misreading that would send an operator looking in entirely the
    // wrong place. No customer is out of pocket here.
    const [item] = connectRecoveryItems([owed()])
    assert.match(item.label, /member was refunded/)
  })

  test('says why the money is outstanding', () => {
    const [item] = connectRecoveryItems([owed()])
    assert.match(item.label, /could not take the creator’s share back/)
  })

  test('never claims the refund failed', () => {
    const label = connectRecoveryItems([owed()])[0].label.toLowerCase()
    for (const wrong of ['refund failed', 'failed refund', 'payment failed']) {
      assert.ok(!label.includes(wrong), `must not say "${wrong}"`)
    }
  })

  test('critical, because it is outstanding money and not a prompt', () => {
    assert.equal(connectRecoveryItems([owed()])[0].severity, 'critical')
  })

  test('a single transaction links straight to that payment', () => {
    const [item] = connectRecoveryItems([owed()])
    assert.equal(item.href, '/admin/payments?txn=txn_abc')
  })

  test('several link to the payments list instead', () => {
    const [item] = connectRecoveryItems([
      owed({ transaction_count: 3, sample_transaction_id: null, outstanding_cents: 500 }),
    ])
    assert.equal(item.href, '/admin/payments')
    assert.match(item.label, /3 refunded sales/)
  })

  test('one sale reads as singular', () => {
    assert.match(connectRecoveryItems([owed()])[0].label, /a refunded sale/)
  })

  test('the amount is formatted in the row’s own currency', () => {
    const [item] = connectRecoveryItems([
      owed({ currency: 'NZD', outstanding_cents: 200 }),
    ])
    assert.match(item.label, /2\.00/)
  })

  test('nothing owed means no line — this is how it clears', () => {
    // The backend drops the row once recovery completes or the amount
    // reaches zero, so an empty list is the resolved state.
    assert.deepEqual(connectRecoveryItems([]), [])
    assert.deepEqual(connectRecoveryItems(undefined), [])
  })

  test('one line per creator and currency', () => {
    const items = connectRecoveryItems([
      owed({ creator_user_id: 'usr_1', currency: 'AUD' }),
      owed({ creator_user_id: 'usr_1', currency: 'NZD', outstanding_cents: 200 }),
      owed({ creator_user_id: 'usr_2', creator_name: 'Grace' }),
    ])
    assert.equal(items.length, 3)
  })
})
