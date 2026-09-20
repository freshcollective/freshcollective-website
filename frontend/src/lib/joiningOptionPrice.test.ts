import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  joiningOptionPriceLabel,
  purchasabilityWarning,
  type JoiningOptionSchedule,
} from './joiningOptionPrice.ts'

/**
 * What the creator reads beside a nominated joining door.
 *
 * The defect these pin down: the panel read the Option's own price
 * columns, which are NULL on every Option authored through the
 * commerce UI, so three live $180–$378 options reported "No price
 * set" beside a ticked checkbox — reporting a broken configuration
 * at the moment it began working.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

function payInFull(cents: number): JoiningOptionSchedule {
  return {
    schedule_type: 'pay_in_full', total_amount_cents: cents,
    installment_amount_cents: null, installment_count: null,
    interval: null, currency: 'AUD', name: 'Pay in full',
    is_member_checkoutable: true,
  }
}

function weekly(total: number, per: number, count: number): JoiningOptionSchedule {
  return {
    schedule_type: 'recurring_installments', total_amount_cents: total,
    installment_amount_cents: per, installment_count: count,
    interval: 'week', currency: 'AUD', name: 'Weekly payments',
    is_member_checkoutable: true,
  }
}

/**
 * EMBODY's three live doors, in the exact shape production serves:
 * the Option's own price columns are absent, and the money lives
 * entirely on the schedules.
 */
const PRODUCTION_DOORS = [
  { name: 'Awaken',   total: 18000, per: 1800, count: 10 },
  { name: 'Activate', total: 30600, per: 3060, count: 10 },
  { name: 'Empower',  total: 37800, per: 3780, count: 10 },
].map((d) => ({
  name: d.name,
  currency: 'AUD',
  // Exactly what the creator API returns for these rows.
  effective_price_cents: null,
  purchasability: 'ready',
  purchasability_notes: [] as string[],
  schedules: [payInFull(d.total), weekly(d.total, d.per, d.count)],
}))

describe('the production shape', () => {
  test('all three EMBODY doors price from their schedules', () => {
    // The screenshot said "No price set" three times. This is that
    // screenshot, as an assertion.
    const labels = PRODUCTION_DOORS.map(joiningOptionPriceLabel)
    assert.deepEqual(labels, [
      '$180 once or 10 weekly payments of $18',
      '$306 once or 10 weekly payments of $30.60',
      '$378 once or 10 weekly payments of $37.80',
    ])
    for (const label of labels) {
      assert.ok(!label.includes('No price set'))
    }
  })

  test('a null effective_price_cents is not an absent price', () => {
    // The precise confusion behind the bug: the Option carries no
    // figure of its own, and that says nothing about whether it sells.
    for (const door of PRODUCTION_DOORS) {
      assert.equal(door.effective_price_cents, null)
      assert.notEqual(joiningOptionPriceLabel(door), 'No price set')
    }
  })

  test('none of them warns the creator', () => {
    for (const door of PRODUCTION_DOORS) {
      assert.equal(purchasabilityWarning(door), null)
    }
  })
})

describe('where the price comes from', () => {
  test('pay-in-full alone reads as a single figure', () => {
    assert.equal(
      joiningOptionPriceLabel({ currency: 'AUD', schedules: [payInFull(18000)] }),
      '$180 once',
    )
  })

  test('a plan alone reads as the instalments', () => {
    assert.equal(
      joiningOptionPriceLabel({ currency: 'AUD', schedules: [weekly(18000, 1800, 10)] }),
      '10 weekly payments of $18',
    )
  })

  test('a schedule the backend refuses is not priced', () => {
    // The surface reads the flag; it must not re-decide.
    const gated = { ...weekly(18000, 1800, 10), is_member_checkoutable: false }
    assert.equal(
      joiningOptionPriceLabel({
        currency: 'AUD', schedules: [payInFull(18000), gated],
      }),
      '$180 once',
    )
  })

  test('legacy option figures never override a real schedule', () => {
    // If they did, this would print $999.
    assert.equal(
      joiningOptionPriceLabel({
        currency: 'AUD',
        effective_price_cents: 99900,
        schedules: [payInFull(18000)],
      }),
      '$180 once',
    )
  })
})

describe('the honest fallbacks', () => {
  test('no usable schedule falls back to the option figure', () => {
    assert.equal(
      joiningOptionPriceLabel({
        currency: 'AUD', schedules: [], effective_price_cents: 4500,
      }),
      '$45 AUD',
    )
  })

  test('a free option says so', () => {
    assert.equal(
      joiningOptionPriceLabel({
        currency: 'AUD', schedules: [], effective_price_cents: 0,
      }),
      'Free',
    )
  })

  test('"No price set" survives only for a genuinely priceless option', () => {
    assert.equal(
      joiningOptionPriceLabel({ currency: 'AUD', schedules: [] }),
      'No price set',
    )
    assert.equal(joiningOptionPriceLabel({ currency: 'AUD' }), 'No price set')
  })
})

describe('telling a creator when a door cannot sell', () => {
  test('a ready option says nothing', () => {
    assert.equal(purchasabilityWarning({ purchasability: 'ready' }), null)
    assert.equal(purchasabilityWarning({}), null)
  })

  test('the backend reason is preferred over our own wording', () => {
    assert.match(
      purchasabilityWarning({
        purchasability: 'needs_attention',
        purchasability_notes: ['No published payment method.'],
      }) ?? '',
      /No published payment method/,
    )
  })

  test('a gated payment plan explains itself rather than looking healthy', () => {
    assert.match(
      purchasabilityWarning({ purchasability: 'configured_not_yet_checkoutable' }) ?? '',
      /not purchasable by members right now/,
    )
  })

  test('an unexplained bad state still warns', () => {
    assert.match(
      purchasabilityWarning({ purchasability: 'needs_attention' }) ?? '',
      /Not currently purchasable/,
    )
  })
})

describe('the panel sources its display from schedules', () => {
  const form = () => read('app/creator-studio/settings/JoinPolicyForm.tsx')

  test('the legacy columns are no longer read', () => {
    // Banned as a field access, not as a word — the module documents
    // in prose why those columns are the wrong source.
    const src = form()
    assert.ok(!/\.override_total_cents/.test(src), 'legacy column read')
    assert.ok(!/\.calculated_total_cents/.test(src), 'legacy column read')
  })

  test('it consumes the fields the API already returns', () => {
    const src = form()
    for (const field of [
      'schedules', 'effective_price_cents',
      'purchasability', 'purchasability_notes',
    ]) {
      assert.ok(src.includes(field), `${field} is not consumed`)
    }
  })

  test('it uses the shared helper rather than its own arithmetic', () => {
    const src = form()
    assert.match(src, /joiningOptionPriceLabel\(option\)/)
    assert.match(src, /purchasabilityWarning\(option\)/)
  })

  test('creator and member read the same words', () => {
    // Two surfaces phrasing one commitment differently is how this
    // whole area went wrong in the first place.
    const helper = read('lib/joiningOptionPrice.ts')
    const doors = read('app/spaces/[slug]/about/JoiningDoors.tsx')
    for (const src of [helper, doors]) {
      assert.match(src, /scheduleShortDescription/)
      assert.match(src, /is_member_checkoutable/)
    }
  })
})
