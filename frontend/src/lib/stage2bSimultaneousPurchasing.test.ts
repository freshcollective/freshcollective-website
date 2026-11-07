import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Stage 2B — individual purchase alongside Payment Options.
 *
 * The safety property these assert is narrow and specific: **while the
 * gate is shut, every one of these surfaces behaves exactly as it did
 * before Stage 2B existed.** Each one therefore has to branch on the
 * flag rather than on the mere presence of a price, and must take its
 * availability answer from the backend instead of deriving one.
 *
 * Asserted against source for the reason the sibling Stage 0 file
 * gives: these are server components and the harness is node:test with
 * no DOM. Absence checks read comment-stripped source — ban the use,
 * not the word.
 *
 * The behaviour itself lives in the backend and is pinned by
 * `backend/tests/test_pathway_simultaneous_purchasing.py`, including
 * the A$5/A$2 incident and the amount the till actually charges.
 */

const SRC = join(process.cwd(), 'src')
const CHECKOUT = join(SRC, 'app', 'spaces', '[slug]', 'pathways', '[pathway-slug]', 'checkout', 'page.tsx')
const ABOUT = join(SRC, 'app', 'spaces', '[slug]', 'pathways', '[pathway-slug]', 'about', 'page.tsx')
const SETTINGS = join(SRC, 'app', 'creator-studio', 'pathways', '[pathwaySlug]', 'PathwaySettingsClient.tsx')
const WAYS_TO_JOIN = join(SRC, 'components', 'commerce', 'PathwayWaysToJoin.tsx')

const read = (p: string) => readFileSync(p, 'utf8')
/** Comment-stripped, so a rule named in prose is not mistaken for one
 *  in force. */
const code = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')

describe('the gate is what decides, on every surface', () => {
  for (const [label, file] of [
    ['member checkout', CHECKOUT],
    ['member about', ABOUT],
  ] as const) {
    it(`${label} reads the flag, not the presence of a price`, () => {
      const src = code(file)
      assert.match(
        src,
        /multiple_purchase_options_enabled === true/,
        'the surface does not consult the Stage 2B gate',
      )
      // The fallback must be the pre-Stage-2B rule, so flag-off is
      // byte-for-byte the old behaviour.
      assert.match(src, /isPaymentOptionsMode/)
    })
  }

  it('member surfaces take availability from the backend', () => {
    // The one rule that must not be re-derived in the browser: a price
    // can be stored on a Pathway nobody may buy individually, so
    // "price_cents is set" is not an offer. The backend answers with
    // the same rule the till applies.
    for (const file of [CHECKOUT, ABOUT]) {
      const src = code(file)
      assert.match(src, /direct_purchase_available === true/)
    }
  })

  it('both surfaces render the arrangements the backend resolved', () => {
    // Stage 2C moved the dual-door decision off these pages. They
    // used to each work out whether to show both doors from the
    // payload's loose fields; now the backend resolves the list and
    // both pages render it with one component, which is what stops
    // them disagreeing about a price or an availability.
    for (const file of [CHECKOUT, ABOUT]) {
      const src = code(file)
      assert.match(src, /ways_to_join/)
      assert.match(src, /PathwayWaysToJoin/)
    }
  })

  it('the member sees each arrangement priced separately', () => {
    // §15: a bundle may include more than this Pathway, and must not
    // be presented as though it were the same purchase. The copy now
    // lives in the shared component — one wording for both surfaces.
    const src = read(WAYS_TO_JOIN)
    assert.match(src, /Purchase this Pathway/)
    assert.match(src, /Also includes/)
    assert.match(src, /Access to this Pathway only/)
  })
})

describe('the creator control', () => {
  it('is only offered once the gate is open', () => {
    const src = code(SETTINGS)
    const i = src.indexOf('simultaneousPurchasing && (')
    assert.ok(i > -1, 'the toggle is not gated')
    assert.match(src, /id="pathway-direct-purchase"/)
  })

  it('is only sent to the API while the gate is open', () => {
    // The API refuses the field with the gate shut, deliberately —
    // the column is a server-maintained mirror there. Sending it
    // anyway would turn every save into a 400.
    const src = code(SETTINGS)
    const i = src.indexOf('body.direct_purchase_enabled')
    assert.ok(i > -1, 'the creator choice is never sent')
    const guard = src.slice(Math.max(0, i - 200), i)
    assert.match(guard, /simultaneousPurchasing/)
  })

  it('stops treating an Option as a blocker once the gate is open', () => {
    // Before Stage 2B an Option pricing the Pathway meant the direct
    // choice could not be offered at all. That exclusivity is exactly
    // what the gate lifts.
    const src = code(SETTINGS)
    const i = src.indexOf('const optionsBlockDirect')
    assert.ok(i > -1)
    const decl = src.slice(i, src.indexOf('\n', i))
    assert.match(decl, /isPaymentOptionsMode && !simultaneousPurchasing/)
  })

  it('still refuses to offer subscription', () => {
    // Unchanged by Stage 2B and asserted here too, because this is the
    // file that decides what the Access list contains: checkout
    // accepts only `one_time`, so a subscription Pathway would be
    // unsellable by any door.
    const src = code(SETTINGS)
    const i = src.indexOf('const CHOICES')
    const block = src.slice(i, src.indexOf(']', src.indexOf('[', i)))
    assert.ok(
      !block.includes("value: 'subscription'"),
      'Pathway Settings offers subscription again',
    )
  })
})

describe('the About headline', () => {
  it('names the cheapest open door, in its own currency', () => {
    const src = code(ABOUT)
    assert.match(src, /lowestOpenPrice/)
    // This surface printed "From $5 AUD" for every Collective,
    // including those selling in USD. `formatMoneyCents`
    // disambiguates — A$5 / US$5 — and is what every other purchase
    // surface uses.
    assert.match(src, /formatMoneyCents/)
    assert.ok(
      !/AUD`/.test(src),
      'the About headline hardcodes a currency again',
    )
  })
})
