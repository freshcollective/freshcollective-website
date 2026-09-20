import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  formatCollectiveAccessLabel,
  formatCollectivePricingSummary,
} from './pricing.ts'

/**
 * What the public pages say about joining.
 *
 * `pricing_type` and `join_policy` answer different questions and can
 * legitimately disagree. EMBODY charges nothing for membership itself
 * (`pricing_type: 'free'`) but membership only arrives with a term
 * purchase (`join_policy: 'purchase_required'`), so the About page
 * said "Free to join" in one column and "Membership comes with your
 * first purchase" in another.
 *
 * The policy is authoritative for any claim about *joining*. Nothing
 * else about pricing display changes.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/** EMBODY as production serves it. */
const embody = {
  pricing_type: 'free' as const,
  pricing_amount_cents: null,
  pricing_currency: 'AUD',
  join_policy: 'purchase_required' as const,
  has_paid_internal_content: true,
  paid_content_summary:
    'EMBODY term access and in-person session bookings are paid separately',
  min_paid_pathway_price_cents: null,
}

const openCollective = { ...embody, join_policy: 'open' as const }

describe('a purchase-required Collective', () => {
  test('does not claim to be free to join', () => {
    // The reported inconsistency, as an assertion.
    assert.equal(
      formatCollectiveAccessLabel(embody),
      'Membership comes with a purchase',
    )
    assert.ok(!formatCollectiveAccessLabel(embody).includes('Free to join'))
  })

  test('says the same thing in the quick-facts row', () => {
    assert.equal(
      formatCollectivePricingSummary(embody),
      'Membership comes with a purchase',
    )
  })

  test('does not append a second, competing price', () => {
    // "Membership comes with a purchase · pathways from $18" would
    // read as two different prices for one doorway.
    const summary = formatCollectivePricingSummary({
      ...embody, min_paid_pathway_price_cents: 1800,
    })
    assert.ok(!summary.includes('·'), summary)
  })

  test('the policy wins even when pricing_type says something else', () => {
    for (const pricing_type of
      ['free', 'paid_one_time', 'paid_monthly', 'invite_only', 'coming_soon'] as const) {
      assert.equal(
        formatCollectiveAccessLabel({ ...embody, pricing_type }),
        'Membership comes with a purchase',
        pricing_type,
      )
    }
  })
})

describe('an open Collective is untouched', () => {
  test('still reads Free to join', () => {
    assert.equal(formatCollectiveAccessLabel(openCollective), 'Free to join')
  })

  test('still gets its paid-content suffix', () => {
    const summary = formatCollectivePricingSummary(openCollective)
    assert.match(summary, /^Free to join · /)
    assert.match(summary, /term access and in-person session bookings are paid separately$/)
  })

  test('the suffix lower-cases its first letter, acronyms included', () => {
    // Pinning existing behaviour, not endorsing it: `inlineCase`
    // lower-cases unconditionally, so a creator's "EMBODY term
    // access…" renders as "eMBODY term access…". Pre-existing and
    // untouched here — changing it would rewrite public copy that
    // nobody asked me to rewrite. Reported separately.
    assert.match(
      formatCollectivePricingSummary(openCollective),
      /· eMBODY term access/,
    )
  })

  test('a Collective that has never heard of join_policy behaves as before', () => {
    // Every existing Collective, and any caller that has not hydrated
    // the field.
    const legacy = { ...embody, join_policy: undefined }
    assert.equal(formatCollectiveAccessLabel(legacy), 'Free to join')
    const nulled = { ...embody, join_policy: null }
    assert.equal(formatCollectiveAccessLabel(nulled), 'Free to join')
  })

  test('every other pricing_type still renders exactly as it did', () => {
    const base = { ...openCollective, has_paid_internal_content: false,
      paid_content_summary: null }
    assert.equal(formatCollectiveAccessLabel(base), 'Free to join')
    assert.equal(formatCollectiveAccessLabel(
      { ...base, pricing_type: 'invite_only' }), 'Invite only')
    assert.equal(formatCollectiveAccessLabel(
      { ...base, pricing_type: 'coming_soon' }), 'Paid — coming soon')
    assert.equal(formatCollectiveAccessLabel(
      { ...base, pricing_type: 'paid_one_time', pricing_amount_cents: 4500 }),
      '$45 AUD')
    assert.equal(formatCollectiveAccessLabel(
      { ...base, pricing_type: 'paid_monthly', pricing_amount_cents: 2000 }),
      '$20 AUD / month')
    assert.equal(formatCollectivePricingSummary(base), 'Free to join · all included')
  })
})

describe('every surface that states the joining cost', () => {
  test('the About Access card and quick-facts row use these helpers', () => {
    const page = read('app/spaces/[slug]/about/page.tsx')
    assert.match(page, /formatCollectiveAccessLabel\(space\)/)
    assert.match(page, /formatCollectivePricingSummary\(\{ \.\.\.space/)
  })

  test('the Explore card does too', () => {
    assert.match(
      read('components/explore/CollectiveCard.tsx'),
      /formatCollectivePricingSummary\(space\)/,
    )
  })

  test('and the Explore card is given the policy to read', () => {
    // It consumes PublicSpaceCard, which had no join_policy — so the
    // card said "Free to join" for EMBODY with no way to know better.
    const types = read('types/platform.ts')
    const block = types.slice(
      types.indexOf('export interface PublicSpaceCard {'),
    )
    assert.match(block.slice(0, block.indexOf('\n}')), /join_policy\?: JoinPolicy/)
    // toSpaceWithMeta spreads the card, so nothing drops it in transit.
    assert.match(read('components/explore/spaceMeta.ts'), /\.\.\.card/)
  })

  test('pricing display is not rewritten, only the joining claim', () => {
    const src = read('lib/pricing.ts')
    // The pricing_type switch survives intact for everything that is
    // genuinely about price rather than about joining.
    for (const kept of
      ['paid_one_time', 'paid_monthly', 'paid_annual', 'invite_only', 'coming_soon']) {
      assert.ok(src.includes(kept), `${kept} handling was removed`)
    }
    assert.match(src, /min_paid_pathway_price_cents/)
    assert.match(src, /paid_content_summary/)
  })
})
