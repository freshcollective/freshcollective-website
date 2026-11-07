import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Stage 0 — what a creator is told about paid access.
 *
 * Three things the payment audit found, all of them about surfaces
 * rather than payment logic:
 *
 *   1. A creator could add an individual Gathering to a Payment
 *      Option, publish it, and have every purchase refused with a
 *      400. Nothing warned them.
 *   2. **New Pathway** offered "One-off payment" and "Monthly
 *      subscription" with a price box, while **Pathway Settings**
 *      called those legacy and refused to write them — so a creator
 *      could create a $49 Pathway and then be told that is not how
 *      paid Pathways work.
 *   3. Nothing anywhere explained the difference between a direct
 *      price and a Payment Option.
 *
 * Asserted against source, for the reason `gatheringPublicLocation.test.ts`
 * gives: these are React components and the harness is node:test with
 * no DOM. Absence checks read comment-stripped source — ban the use,
 * not the word.
 *
 * The *behaviour* lives in the backend and is pinned by
 * `backend/tests/test_stage0_unsupported_grant_safety.py`. This file
 * only asserts that the creator can see it.
 */

const SRC = join(process.cwd(), 'src')
const PO_INDEX = join(SRC, 'app', 'creator-studio', 'payment-options', 'PaymentOptionsIndexClient.tsx')
const PO_EDITOR = join(SRC, 'app', 'creator-studio', 'payment-options', '[optionId]', 'PaymentOptionEditorClient.tsx')
const PATHWAY_NEW = join(SRC, 'app', 'creator-studio', 'pathways', 'new', 'NewPathwayClient.tsx')
const PATHWAY_SETTINGS = join(SRC, 'app', 'creator-studio', 'pathways', '[pathwaySlug]', 'PathwaySettingsClient.tsx')
const GATHERING = join(SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'EventForm.tsx')

const read = (p: string) => readFileSync(p, 'utf8')

/** Source with comments removed, so an absence check reads the code. */
function code(p: string): string {
  return read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

describe('an unsupported Gathering inclusion is visible to the creator', () => {
  it('the new purchasability state is in the shared type', () => {
    // Both the index and the editor read `PaymentOptionRow`, so one
    // union covers both surfaces.
    assert.match(read(PO_INDEX), /'unsupported_inclusion'/)
  })

  it('the Payment Options list badges it without calling it broken', () => {
    const src = read(PO_INDEX)
    const i = src.indexOf("row.purchasability === 'unsupported_inclusion'")
    assert.ok(i > 0, 'the index has no branch for the new state')
    const branch = src.slice(i, i + 700)
    assert.match(branch, /Not purchasable yet/)
    // Amber, not red: nothing is broken and nothing needs repairing.
    assert.match(branch, /amber/)
    assert.ok(!/\bred-\d/.test(branch), 'the badge reads as an error')
  })

  it('the editor explains it with the agreed wording', () => {
    const src = read(PO_EDITOR)
    const i = src.indexOf("option.purchasability === 'unsupported_inclusion'")
    assert.ok(i > 0, 'the editor has no branch for the new state')
    const branch = src.slice(i, i + 1400)
    assert.match(branch, /Individual Gathering payments through Payment Options are/)
    assert.match(branch, /coming soon/)
    assert.match(branch, /cannot purchase it/)
    // Says what to do instead.
    assert.match(branch, /Gathering editor/)
  })

  it('and the grant row itself warns, before anybody publishes', () => {
    // The banner is reachable only once the option is loaded; this is
    // the warning attached to the thing the creator just added.
    const src = read(PO_EDITOR)
    const i = src.indexOf("grant.grant_kind === 'gathering'")
    assert.ok(i > 0, 'the gathering grant row carries no warning')
    const branch = src.slice(i, i + 900)
    assert.match(branch, /Not purchasable yet/)
    assert.match(branch, /coming soon/)
    // The sharp edge worth naming: one Gathering blocks the whole
    // option, not just its own line.
    assert.match(branch, /no payment method on this option/)
  })

  it('nothing offers to enable Gathering payments', () => {
    // Stage 0 removes a dead end; it must not advertise the feature
    // as switchable-on, or offer a control for it.
    const editor = code(PO_EDITOR)
    assert.ok(!/enable.{0,24}Gathering payment/i.test(editor))
  })
})

describe('the two Pathway surfaces agree', () => {
  it('New Pathway offers only choices Settings can maintain', () => {
    // Stage 2A moved `one_time` across this line. Stage 0 removed it
    // because Settings could not maintain a direct price; Settings now
    // can, so offering it at creation is no longer a trap.
    //
    // `subscription` stays out, and this is the assertion that keeps it
    // out: `POST /api/checkout/pathway` refuses anything but
    // `one_time`, so a subscription Pathway is unsellable by any door.
    const src = code(PATHWAY_NEW)
    const i = src.indexOf('ACCESS_OPTIONS')
    const block = src.slice(i, src.indexOf(']', src.indexOf('[', i)))
    for (const v of ["'free'", "'included'", "'included_with_offer'", "'one_time'"]) {
      assert.ok(block.includes(v), `New Pathway no longer offers ${v}`)
    }
    assert.ok(
      !block.includes("'subscription'"),
      'New Pathway offers subscription again, which checkout refuses to sell',
    )
  })

  it('both surfaces use the same three labels', () => {
    for (const f of [PATHWAY_NEW, PATHWAY_SETTINGS]) {
      const src = read(f)
      assert.match(src, /label: 'Public'/)
      assert.match(src, /label: 'Members only'/)
      assert.match(src, /label: 'Payment Option access'/)
    }
  })

  it('the direct-price control is live again, and only for one_time', () => {
    // Stage 0 kept this control dormant for Stage 2. Stage 2 is here:
    // it renders, and the condition that renders it must not readmit
    // `subscription` by the back door.
    const src = code(PATHWAY_NEW)
    assert.match(src, /\{isPaid && \(/)
    const i = src.indexOf('const isPaid')
    const decl = src.slice(i, src.indexOf('\n', i))
    assert.match(decl, /accessType === 'one_time'/)
    assert.ok(
      !decl.includes("'subscription'"),
      'the price box renders for subscription, which cannot be sold',
    )
  })

  it('Settings lets a direct-priced Pathway edit its price', () => {
    // Stage 0's banner explained why the price could not be edited
    // here. Stage 2A replaced the banner with the control, so the
    // contract is now the control itself: an editable amount, bound to
    // the price state, rendered only for `one_time`.
    const src = code(PATHWAY_SETTINGS)
    assert.match(src, /id="pathway-price"/)
    assert.match(src, /value=\{priceDollars\}/)
    assert.match(src, /onChange=\{\(e\) => setPriceDollars\(e\.target\.value\)\}/)
    const i = src.indexOf('const showPrice')
    const decl = src.slice(i, src.indexOf('\n', i))
    assert.match(decl, /accessType === 'one_time'/)
    // Withheld while an Option prices the Pathway — but only while the
    // Stage 2B gate is shut, which is what `optionsBlockDirect` means.
    // Stage 2B's whole purpose is that both can be live at once.
    assert.match(decl, /!optionsBlockDirect/)
    const j = src.indexOf('const optionsBlockDirect')
    const gate = src.slice(j, src.indexOf('\n', j))
    assert.match(gate, /isPaymentOptionsMode && !simultaneousPurchasing/)
  })

  it('and still explains itself when an Option prices the Pathway', () => {
    // The one case where a direct price is withheld: an Option
    // already answers "what does this cost". Showing both is the
    // conflict `pricing_mode` exists to prevent, so the creator is
    // told why the box is absent and how to get it back.
    const src = read(PATHWAY_SETTINGS)
    assert.match(src, /A Payment Option prices this Pathway/)
    assert.match(src, /completed purchases are\s*\n?\s*untouched/)
  })

  it('and the currency is not editable once a price exists', () => {
    // Enforced server-side in `update_pathway`; this is the matching
    // creator-facing half, so the field a creator can see agrees with
    // what the API will accept.
    const src = code(PATHWAY_SETTINGS)
    assert.match(src, /setCurrency: _setCurrency/)
    assert.match(src, /currencyLabel/)
    assert.ok(
      !/onChange=\{\(e\) => setCurrency\(/.test(src),
      'Pathway Settings writes a currency again',
    )
  })

  it('and still refuses to write a paid access type', () => {
    // The protection the audit asked us not to weaken. `pricing_mode`
    // is set to 'legacy' and the access type comes from CHOICES, none
    // of which is a paid value.
    const src = code(PATHWAY_SETTINGS)
    assert.match(src, /function handleChoiceClick/)
    const i = src.indexOf('function handleChoiceClick')
    const fn = src.slice(i, i + 260)
    assert.match(fn, /setPricingMode\('legacy'\)/)
  })
})

describe('creators are told what a direct price is for, and what Payment Options are for', () => {
  it('New Pathway explains Payment Options when that choice is made', () => {
    const src = read(PATHWAY_NEW)
    assert.match(src, /How paid access works/)
    assert.match(src, /single\s*\n?\s*payment or a payment plan/)
  })

  it('Pathway Settings says the same thing', () => {
    const src = read(PATHWAY_SETTINGS)
    assert.match(src, /How paid access works/)
    assert.match(src, /single\s*\n?\s*payment or a payment plan/)
  })

  it('the Gathering editor names its ticket a one-time purchase', () => {
    const src = read(GATHERING)
    assert.match(src, /one-time purchase/)
    assert.match(src, /pay\s*\n?\s*once for this Gathering/)
  })

  it('and is honest that Gathering instalments are not available', () => {
    // §4: do not introduce controls for purchasing methods that
    // aren't operational. So the Gathering editor explains where
    // Payment Options apply today and does not offer them here.
    const src = read(GATHERING)
    assert.match(src, /covers Pathways and Gathering Series today/)
    assert.match(src, /Instalments for an individual Gathering are coming/)
    assert.match(src, /a ticket price here is how a single Gathering is sold/)
  })

  it('the Payment Options editor points single sales back to the experience', () => {
    const src = read(PO_EDITOR)
    assert.match(src, /bundles, payment plans and other arrangements live/)
    assert.match(src, /set a price in that/)
  })

  it('the distinction is drawn by scope, not by payment count', () => {
    // A Payment Option can be a single payment too, so "one-time vs
    // instalments" would be the wrong line. What separates them is
    // how many experiences one arrangement can cover.
    assert.match(read(PATHWAY_NEW), /One Option can cover several experiences/)
    assert.match(read(PATHWAY_SETTINGS), /One Option can cover several experiences/)
  })
})
