import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  formatAccessFallbackCopy,
  formatCollectiveAccessLabel,
  formatCollectivePricingSummary,
  formatPaidSeparatelyCopy,
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

  test("an acronym in the suffix keeps its capitals", () => {
    // A creator's own Collective name, misspelt by us, on the page
    // that introduces it.
    assert.match(
      formatCollectivePricingSummary(openCollective),
      /· EMBODY term access/,
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
    // Was `formatCollectivePricingSummary({ ...space` — the spread
    // existed to override min_paid_pathway_price_cents with a locally
    // derived value, which is the bug. The space is now passed as the
    // backend served it.
    assert.match(page, /formatCollectivePricingSummary\(space\)/)
    assert.match(page, /formatPaidSeparatelyCopy\(space\)/)
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


describe('the inline suffix, character by character', () => {
  /** The suffix is only reachable through the summary, so drive it
   *  from there rather than exporting a private helper for tests. */
  const suffixFor = (paid_content_summary: string) =>
    formatCollectivePricingSummary({
      ...openCollective, paid_content_summary,
    }).replace('Free to join · ', '')

  test('ordinary sentence case is lower-cased, as it always was', () => {
    assert.equal(suffixFor('Paid pathways available'), 'paid pathways available')
    assert.equal(suffixFor('Term passes sold separately'), 'term passes sold separately')
  })

  test('two leading capitals mean an acronym or proper name — left alone', () => {
    assert.equal(suffixFor('EMBODY term access'), 'EMBODY term access')
    assert.equal(suffixFor('AI resources available'), 'AI resources available')
    assert.equal(suffixFor('NHS-funded places'), 'NHS-funded places')
  })

  test('a single leading capital is still ordinary sentence case', () => {
    // The distinction the rule turns on: one capital is a sentence,
    // two is a name.
    assert.equal(suffixFor('Access sold separately'), 'access sold separately')
    assert.equal(suffixFor('A few paid extras'), 'a few paid extras')
  })

  test('copy that already starts lower-case is unchanged', () => {
    assert.equal(suffixFor('paid pathways available'), 'paid pathways available')
  })

  test('a non-letter opening is left exactly as written', () => {
    assert.equal(suffixFor('3 paid pathways'), '3 paid pathways')
    assert.equal(suffixFor('$20 term passes'), '$20 term passes')
    assert.equal(suffixFor('“Deep Dive” sold separately'), '“Deep Dive” sold separately')
  })

  test('a one-character summary does not crash', () => {
    assert.equal(suffixFor('X'), 'x')
  })

  test('accented capitals count as capitals', () => {
    assert.equal(suffixFor('ÉCOLE sessions'), 'ÉCOLE sessions')
    assert.equal(suffixFor('Élan sessions'), 'élan sessions')
  })
})


/**
 * Stale legacy pricing on the public About page.
 *
 * Production, as reported: Test Pathway sits at
 * ``pricing_mode='payment_options'`` and still carries
 * ``price_cents=500`` in the legacy column the switch left behind. Its
 * live price is a published Payment Option — Test Connect Instalments,
 * two weekly payments of $2, $4 committed — whose own
 * ``override_total_cents`` and ``calculated_total_cents`` are both
 * NULL, because the commerce UI treats schedules as the source of
 * truth.
 *
 * The backend now derives 400 from that schedule and serves it as
 * ``min_paid_pathway_price_cents``. Two things had to be fixed for this
 * number to reach the page: it threw the backend value away and
 * re-derived its own from ``pathway.price_cents`` (advertising $5), and
 * before that the backend's own derivation read the Option's NULL
 * authoring columns (advertising nothing at all).
 *
 * $4 is the total commitment, not the $2 instalment: a visitor
 * comparing Collectives is comparing what they are signing up for.
 */
describe('a payment-options Pathway with a stale legacy price', () => {
  /** The Collective as the detail endpoint serves it. */
  const staleCollective = {
    ...openCollective,
    paid_content_summary: null,
    has_paid_internal_content: true,
    // The backend's answer: the published plan's total commitment.
    min_paid_pathway_price_cents: 400,
    // The stale column, present in the payload and now unread. Kept in
    // the fixture precisely because the bug was reading it.
    pathways: [{
      title: 'Test Pathway',
      status: 'active',
      access_type: 'one_time',
      pricing_mode: 'payment_options',
      price_cents: 500,
    }],
  }

  test('the quick-facts row quotes $4, never $5', () => {
    const summary = formatCollectivePricingSummary(staleCollective)
    assert.equal(summary, 'Free to join · pathways from $4 AUD')
    assert.ok(!summary.includes('$5'), summary)
  })

  test('the Access card quotes $4, never $5', () => {
    // The second place the stale price surfaced on the same page.
    const copy = formatPaidSeparatelyCopy(staleCollective)
    assert.equal(copy, 'Pathways from $4 AUD')
    assert.ok(!copy.includes('$5'), copy)
  })

  test('neither surface falls back to the generic copy', () => {
    // The second reported symptom. A Collective that plainly sells
    // something must not read as though it sells nothing.
    assert.ok(
      !formatPaidSeparatelyCopy(staleCollective)
        .includes('Paid pathways available separately'),
    )
    assert.match(
      formatCollectivePricingSummary(staleCollective),
      /pathways from \$/,
    )
  })

  test('the instalment amount is not the headline', () => {
    // $2 is what leaves the member's account on the first Friday. The
    // commitment is $4, and that is what a comparison surface shows.
    const summary = formatCollectivePricingSummary(staleCollective)
    const copy = formatPaidSeparatelyCopy(staleCollective)
    assert.ok(!summary.includes('$2'), summary)
    assert.ok(!copy.includes('$2'), copy)
  })

  test('the stale column cannot reach either surface', () => {
    // Drive the real failure mode: if anything still derived from
    // price_cents, dropping the backend field would resurrect $5.
    // It must degrade to the generic copy instead.
    const withoutBackendValue = {
      ...staleCollective, min_paid_pathway_price_cents: null,
    }
    const summary = formatCollectivePricingSummary(withoutBackendValue)
    const copy = formatPaidSeparatelyCopy(withoutBackendValue)
    assert.ok(!summary.includes('$5'), summary)
    assert.ok(!copy.includes('$5'), copy)
    assert.equal(copy, 'Paid pathways available separately')
  })
})

describe('an Option priced by its own columns still renders', () => {
  /**
   * The pay-in-full / one-time shape, where ``effective_price_cents``
   * is populated and agrees with the schedule. Retained deliberately:
   * the schedule-aware backend rewrite must not regress the Options
   * that were already priced correctly.
   */
  const payInFullCollective = {
    ...openCollective,
    paid_content_summary: null,
    has_paid_internal_content: true,
    min_paid_pathway_price_cents: 200,
    pathways: [{
      title: 'Pay In Full Pathway',
      status: 'active',
      access_type: 'one_time',
      pricing_mode: 'payment_options',
      price_cents: 200,
    }],
  }

  test('the quick-facts row shows it', () => {
    assert.equal(
      formatCollectivePricingSummary(payInFullCollective),
      'Free to join · pathways from $2 AUD',
    )
  })

  test('the Access card shows it', () => {
    assert.equal(
      formatPaidSeparatelyCopy(payInFullCollective),
      'Pathways from $2 AUD',
    )
  })
})

describe('a legacy Pathway still prices normally', () => {
  const legacyCollective = {
    ...openCollective,
    paid_content_summary: null,
    has_paid_internal_content: true,
    // Legacy mode: the backend derives from price_cents, and the two
    // agree. This is the case that must not regress while fixing the
    // other one.
    min_paid_pathway_price_cents: 1800,
    pathways: [{
      title: 'Legacy Pathway',
      status: 'active',
      access_type: 'one_time',
      pricing_mode: 'legacy',
      price_cents: 1800,
    }],
  }

  test('the quick-facts row shows the backend-derived minimum', () => {
    assert.equal(
      formatCollectivePricingSummary(legacyCollective),
      'Free to join · pathways from $18 AUD',
    )
  })

  test('the Access card shows it too', () => {
    assert.equal(
      formatPaidSeparatelyCopy(legacyCollective),
      'Pathways from $18 AUD',
    )
  })

  test('a Collective with nothing paid inside is unchanged', () => {
    assert.equal(
      formatCollectivePricingSummary({
        ...openCollective,
        has_paid_internal_content: false,
        paid_content_summary: null,
        min_paid_pathway_price_cents: null,
      }),
      'Free to join · all included',
    )
  })
})

describe('creator-supplied copy keeps its precedence', () => {
  test('the Access card prefers the creator summary over any price', () => {
    // Unchanged from the inline version: the creator describing what
    // they sell outranks a derived number.
    assert.equal(
      formatPaidSeparatelyCopy({
        ...openCollective,
        paid_content_summary: 'Term passes sold separately',
        min_paid_pathway_price_cents: 200,
      }),
      'Term passes sold separately',
    )
  })

  test('whitespace-only copy is not treated as copy', () => {
    assert.equal(
      formatPaidSeparatelyCopy({
        ...openCollective,
        paid_content_summary: '   ',
        min_paid_pathway_price_cents: 200,
      }),
      'Pathways from $2 AUD',
    )
  })

  test('the Access card is not lower-cased the way the inline suffix is', () => {
    // It opens a line of its own rather than following "Free to join ·",
    // so sentence case is correct there. Asserted because the two
    // helpers sit next to each other and share a shape.
    assert.equal(
      formatPaidSeparatelyCopy({
        ...openCollective,
        paid_content_summary: 'Paid pathways available',
      }),
      'Paid pathways available',
    )
  })

  test('the quick-facts row still prefers the price for a free Collective', () => {
    // Pre-existing and deliberate asymmetry with the Access card. Pinned
    // so the refactor is visibly not a behaviour change.
    assert.equal(
      formatCollectivePricingSummary({
        ...openCollective,
        paid_content_summary: 'Term passes sold separately',
        min_paid_pathway_price_cents: 200,
      }),
      'Free to join · pathways from $2 AUD',
    )
  })
})

describe('the About page does not re-derive the price', () => {
  /**
   * These match the *use*, not the word. ``price_cents`` still appears
   * in the page's comments — explaining why it is deliberately not read
   * is the thing that stops the derivation coming back — so a blunt
   * ``includes('price_cents')`` check would fail on the documentation
   * rather than on a regression.
   */
  const page = () => read('app/spaces/[slug]/about/page.tsx')

  test('no local minimum is computed over the pathway list', () => {
    assert.ok(!/Math\.min\(/.test(page()), 'a local minimum reappeared')
  })

  test('no pathway price is read in a filter predicate', () => {
    const src = page()
    assert.ok(!/price_cents\s*!=\s*null/.test(src), 'price_cents null-check returned')
    assert.ok(!/price_cents\s*>\s*0/.test(src), 'price_cents > 0 filter returned')
    assert.ok(!/price_cents as number/.test(src), 'price_cents cast returned')
  })

  test('the backend field is what the page reads', () => {
    assert.match(page(), /space\.min_paid_pathway_price_cents/)
  })

  test('and the type system offers it', () => {
    const types = read('types/platform.ts')
    const block = types.slice(types.indexOf('export interface SpaceResponse {'))
    assert.match(
      block.slice(0, block.indexOf('\n}')),
      /min_paid_pathway_price_cents: number \| null/,
    )
  })
})


/**
 * The Access card's line when nothing paid is being described.
 *
 * It used to read "All available content is included." — a claim about
 * the contents of the Collective, derived from a flag about
 * purchasability. Those are not the same thing. A creator can publish
 * paid content that is not currently checkoutable (an instalment plan
 * published before member plans were switched on), and the public flag
 * is false in exactly that case, so the page asserted that everything
 * was included while something published was not.
 *
 * "Joining this Collective is free." answers only what the Access card
 * is asking and makes no claim about what is inside.
 */
describe('the Access card fallback line', () => {
  /** Free to join, nothing paid detected inside. */
  const plainFreeCollective = {
    ...openCollective,
    pricing_note: null,
    paid_content_summary: null,
    has_paid_internal_content: false,
    derived_has_paid_internal_content: false,
    min_paid_pathway_price_cents: null,
  }

  test('a free Collective says what joining costs', () => {
    assert.equal(
      formatAccessFallbackCopy(plainFreeCollective),
      'Joining this Collective is free.',
    )
  })

  test('it no longer claims everything is included', () => {
    // The sentence is gone from what the function returns...
    assert.ok(
      !formatAccessFallbackCopy(plainFreeCollective)
        ?.includes('All available content is included'),
    )

    // ...and from what either file can render. These match the
    // sentence as *code* — a returned string literal, or a JSX text
    // node — not merely as text. Both files now explain in a comment
    // what the old copy was and why it was wrong, and a blunt
    // includes() check fails on that explanation rather than on a
    // regression. Keeping the documentation is worth more than the
    // looser assertion.
    assert.ok(
      !/'All available content is included\.'/.test(read('lib/pricing.ts')),
      'the old sentence is still returned by a helper',
    )
    assert.ok(
      !/>\s*All available content is included\./.test(
        read('app/spaces/[slug]/about/page.tsx'),
      ),
      'the old sentence is still rendered by the page',
    )
  })

  test('it makes no claim about what is inside at all', () => {
    // The point of the change, rather than the wording of it: this line
    // is reached from a purchasability flag, which cannot support a
    // statement about contents either way.
    const copy = formatAccessFallbackCopy(plainFreeCollective) ?? ''
    for (const word of ['included', 'content', 'everything', 'all ']) {
      assert.ok(
        !copy.toLowerCase().includes(word),
        `fallback copy still describes contents: ${copy}`,
      )
    }
  })

  test("the creator's pricing_note still wins", () => {
    assert.equal(
      formatAccessFallbackCopy({
        ...plainFreeCollective,
        pricing_note: 'Sliding scale — pay what you can.',
      }),
      'Sliding scale — pay what you can.',
    )
  })

  test('pricing_note wins on a paid Collective too', () => {
    // Precedence is unchanged, which means it does not depend on
    // pricing_type.
    assert.equal(
      formatAccessFallbackCopy({
        ...plainFreeCollective,
        pricing_type: 'paid_one_time',
        pricing_amount_cents: 4500,
        pricing_note: 'One payment, lifetime access.',
      }),
      'One payment, lifetime access.',
    )
  })

  test('a paid Collective with no note says nothing', () => {
    // The Access label above has already stated the price; repeating it
    // here would read as a second fee.
    assert.equal(
      formatAccessFallbackCopy({
        ...plainFreeCollective,
        pricing_type: 'paid_one_time',
        pricing_amount_cents: 4500,
      }),
      null,
    )
  })

  test('a whitespace-only note is still treated as a note', () => {
    // Pre-existing truthy check, preserved deliberately: trimming here
    // would change which Collectives see their own note, which is not
    // what this change is for.
    assert.equal(formatAccessFallbackCopy({
      ...plainFreeCollective, pricing_note: '   ',
    }), '   ')
  })

  test('the page renders this line and not its own conditional', () => {
    const page = read('app/spaces/[slug]/about/page.tsx')
    assert.match(page, /formatAccessFallbackCopy\(space\)/)
    // The branch used to inline the pricing_note / pricing_type test in
    // JSX, which is why the copy was unreachable from here.
    assert.ok(
      !/space\.pricing_type === 'free' \?/.test(page),
      'the inline pricing_type conditional is back in the JSX',
    )
  })
})

describe('the paid-separately branch is untouched by that change', () => {
  /**
   * Requirement 4, stated as behaviour rather than as a diff: a
   * Collective with paid content inside still goes through
   * ``formatPaidSeparatelyCopy`` and still quotes the backend price.
   */
  const withPaidContent = {
    ...openCollective,
    pricing_note: null,
    paid_content_summary: null,
    has_paid_internal_content: true,
    min_paid_pathway_price_cents: 400,
  }

  test('it still quotes the derived price', () => {
    assert.equal(
      formatPaidSeparatelyCopy(withPaidContent),
      'Pathways from $4 AUD',
    )
  })

  test('it does not fall back to the joining line', () => {
    // The two branches are mutually exclusive in the page; this asserts
    // they also say different things, so a mix-up would be visible.
    assert.notEqual(
      formatPaidSeparatelyCopy(withPaidContent),
      formatAccessFallbackCopy(withPaidContent),
    )
  })

  test('a pricing_note does not leak into the paid-separately line', () => {
    // ``pricing_note`` feeds the fallback only. The paid-separately
    // line has its own creator field, ``paid_content_summary``.
    assert.equal(
      formatPaidSeparatelyCopy({
        ...withPaidContent,
        pricing_note: 'Sliding scale — pay what you can.',
      }),
      'Pathways from $4 AUD',
    )
  })

  test('the page still routes that branch through the helper', () => {
    assert.match(
      read('app/spaces/[slug]/about/page.tsx'),
      /formatPaidSeparatelyCopy\(space\)/,
    )
  })
})
