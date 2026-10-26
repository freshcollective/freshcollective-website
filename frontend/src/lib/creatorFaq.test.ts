import { strict as assert } from 'node:assert'
import { describe, it } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  CREATOR_FAQ,
  FEE_ROWS,
  FEE_TABLE_HEADINGS,
  creatorFaqJsonLd,
  faqSchemaAnswer,
} from './creatorFaq.ts'
import { PUBLIC_PLANS } from './plans.ts'
import { CONTACT_INFO_EMAIL } from './contact.ts'

const SRC = dirname(dirname(fileURLToPath(import.meta.url)))
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const PAGE = 'app/for-creators/page.tsx'

/** Every answer as one string, for whole-FAQ assertions. */
const allCopy = CREATOR_FAQ
  .flatMap((i) => [i.question, ...i.paragraphs])
  .join(' ')

describe('the FAQ content', () => {
  it('has the seven approved questions, in order', () => {
    assert.deepEqual(CREATOR_FAQ.map((i) => i.question), [
      'How do I get paid?',
      'What does the platform fee actually cost me?',
      'Can I start for free?',
      'Can I change or cancel my plan?',
      'Who owns my content?',
      'How do I bring my existing people across?',
      'What happens if a member leaves?',
    ])
  })

  it('every item has a question, an id and at least one paragraph', () => {
    const ids = new Set<string>()
    for (const item of CREATOR_FAQ) {
      assert.ok(item.question.trim(), 'question')
      assert.ok(item.id.trim(), `id for ${item.question}`)
      assert.ok(!ids.has(item.id), `duplicate id ${item.id}`)
      ids.add(item.id)
      assert.ok(item.paragraphs.length > 0, `paragraphs for ${item.question}`)
      for (const p of item.paragraphs) {
        assert.equal(p.trim(), p, 'no stray whitespace')
        assert.ok(!/<[a-z/]/i.test(p), 'answers are plain text, not markup')
      }
    }
  })

  it('uses Australian spelling and typographic apostrophes', () => {
    // The brief asked for Australian spelling. These are the words in
    // this copy where the two diverge.
    for (const american of ['organize', 'organization', 'canceled',
      'cancelation', 'enrollment', 'customize', 'license fee']) {
      assert.ok(!allCopy.toLowerCase().includes(american), american)
    }
    // Curly apostrophes throughout, no ASCII ones left behind.
    assert.ok(allCopy.includes('’'), 'typographic apostrophe present')
    assert.ok(!/\w'\w/.test(allCopy), "no straight apostrophes in words")
  })
})

describe('the figures agree with the plan config', () => {
  // The copy states the percentages and monthly prices as approved
  // rather than deriving them, so these assertions are what stop the
  // page quoting a stale figure after a plan change. The backend row is
  // the source of truth; ``PUBLIC_PLANS`` already trails it and has its
  // own consistency test.
  const fee = CREATOR_FAQ.find((i) => i.id === 'platform-fee')!

  it('quotes the live commission for each plan', () => {
    assert.equal(PUBLIC_PLANS.creator.commissionLabel, '8%')
    assert.equal(PUBLIC_PLANS.pro.commissionLabel, '4%')
    assert.ok(fee.paragraphs[0].includes('8% on the Creator plan'))
    assert.ok(fee.paragraphs[0].includes('4% on Creator Portfolio'))
    assert.ok(FEE_TABLE_HEADINGS.creator.includes('8%'))
    assert.ok(FEE_TABLE_HEADINGS.portfolio.includes('4%'))
  })

  it('quotes the live monthly prices', () => {
    assert.equal(PUBLIC_PLANS.creator.priceLabel, '$19 / month')
    assert.equal(PUBLIC_PLANS.pro.priceLabel, '$79 / month')
    assert.ok(fee.paragraphs.some((p) => p.includes('($19 or $79)')))
  })

  it('the worked examples are the sale less the commission', () => {
    // Arithmetic, not copy: 49 × 0.92, 49 × 0.96, 300 × 0.92, 300 × 0.96.
    const cents = (s: string) => Math.round(parseFloat(s.replace('$', '')) * 100)
    const expected = [
      { sale: 4900 }, { sale: 30000 },
    ]
    FEE_ROWS.forEach((row, i) => {
      const sale = expected[i].sale
      assert.equal(cents(row.creator), Math.round(sale * 0.92), row.sale)
      assert.equal(cents(row.portfolio), Math.round(sale * 0.96), row.sale)
    })
  })

  it('states that processing costs are covered, as the platform does', () => {
    // Verified in the implementation: the creator receives
    // ``net_creator_amount_cents`` and FC absorbs the processing fee out
    // of its own commission.
    assert.ok(fee.paragraphs[0].includes('We cover the standard card processing costs'))
  })
})

describe('what the FAQ must not claim', () => {
  // Each of these was wrong in an earlier draft and was corrected
  // against the implementation. They are asserted as absences so a
  // future edit cannot quietly reintroduce one.

  it('does not say creators avoid having a Stripe account', () => {
    // Creators get a Connect ``recipient`` account with an Express
    // dashboard, and Stripe — not Fresh Collective — collects their
    // bank details.
    assert.ok(!/don.t need a Stripe account/i.test(allCopy))
    assert.ok(!/we pay you directly/i.test(allCopy))
  })

  it('does not promise a deletion or retention deadline', () => {
    // There is no retention window: cancellation deletes nothing.
    assert.ok(!/\b\d+ days?\b/i.test(allCopy), 'no day-count deadline')
    for (const word of ['deleted after', 'permanently removed', 'retention period']) {
      assert.ok(!allCopy.toLowerCase().includes(word), word)
    }
  })

  it('says cancelling deletes nothing', () => {
    const cancel = CREATOR_FAQ.find((i) => i.id === 'change-or-cancel')!
    assert.ok(cancel.paragraphs.some((p) =>
      p.includes('doesn’t delete your Collective or your content')))
  })

  it('does not imply paid offerings must be retired before downgrading', () => {
    // Only the active-Collective limit is a precondition — exceeding it
    // is a 409. Paid offerings are left in place and simply stop
    // selling.
    const cancel = CREATOR_FAQ.find((i) => i.id === 'change-or-cancel')!
    const limits = cancel.paragraphs.find((p) => p.includes('Collective limit'))!
    assert.ok(limits.includes('archive any extras'), 'the real precondition')
    assert.ok(!limits.toLowerCase().includes('offering'),
      'the offerings consequence must not sit in the precondition sentence')
    assert.ok(cancel.paragraphs.some((p) =>
      p.includes('become unavailable when the downgrade takes effect')))
  })

  it('tells a leaving member what they keep, and what keeps running', () => {
    const leaves = CREATOR_FAQ.find((i) => i.id === 'member-leaves')!
    const text = leaves.paragraphs.join(' ')
    for (const kept of ['digital downloads', 'individual Pathways', 'Gatherings']) {
      assert.ok(text.includes(kept), kept)
    }
    assert.ok(/doesn’t automatically cancel an existing subscription or payment plan/
      .test(text))
  })

  it('does not claim bulk member import', () => {
    const bring = CREATOR_FAQ.find((i) => i.id === 'bring-existing-people')!
    assert.ok(bring.paragraphs[0].includes('one at a time'))
    for (const word of ['csv', 'bulk', 'import']) {
      assert.ok(!bring.paragraphs[0].toLowerCase().includes(word), word)
    }
  })
})

describe('the FAQPage structured data', () => {
  const ld = creatorFaqJsonLd() as {
    '@context': string
    '@type': string
    mainEntity: { '@type': string; name: string; acceptedAnswer: { '@type': string; text: string } }[]
  }

  it('is a valid FAQPage shape', () => {
    assert.equal(ld['@context'], 'https://schema.org')
    assert.equal(ld['@type'], 'FAQPage')
    assert.equal(ld.mainEntity.length, CREATOR_FAQ.length)
    for (const q of ld.mainEntity) {
      assert.equal(q['@type'], 'Question')
      assert.equal(q.acceptedAnswer['@type'], 'Answer')
      assert.ok(q.name.trim())
      assert.ok(q.acceptedAnswer.text.trim())
    }
  })

  it('every visible question appears, with the visible wording', () => {
    assert.deepEqual(
      ld.mainEntity.map((q) => q.name),
      CREATOR_FAQ.map((i) => i.question),
    )
  })

  it('answers match the visible copy rather than being written twice', () => {
    // The whole reason the copy lives in one module: a schema answer
    // that says something the page does not is treated as cloaking.
    for (const item of CREATOR_FAQ) {
      const entry = ld.mainEntity.find((q) => q.name === item.question)!
      if (!item.schemaAnswer) {
        assert.equal(entry.acceptedAnswer.text, item.paragraphs.join(' '))
      }
    }
  })

  it('the fee answer states the example in prose instead of a table', () => {
    const fee = ld.mainEntity.find((q) => q.name.includes('platform fee'))!
    const text = fee.acceptedAnswer.text
    assert.ok(text.includes('on a $300 sale you receive $276 on Creator or $288 on Creator Portfolio'))
    assert.ok(!text.includes('Here’s what that looks like'),
      'the trailing table lead-in has no place in a prose answer')
    assert.ok(!/<table|<tr|<td/i.test(text), 'no markup')
    assert.ok(text.includes('($19 or $79) is separate'))
  })

  it('no answer carries markup or newlines', () => {
    for (const q of ld.mainEntity) {
      assert.ok(!/<[a-z/]/i.test(q.acceptedAnswer.text), q.name)
      assert.ok(!/[\n\r]/.test(q.acceptedAnswer.text), q.name)
    }
  })

  it('serialises without breaking out of the script tag', () => {
    // The page injects this with dangerouslySetInnerHTML.
    const json = JSON.stringify(creatorFaqJsonLd())
    assert.ok(!json.includes('</'), 'nothing that could close the script early')
    assert.deepEqual(JSON.parse(json), creatorFaqJsonLd())
  })

  it('faqSchemaAnswer falls back to the paragraphs', () => {
    const plain = CREATOR_FAQ.find((i) => !i.schemaAnswer)!
    assert.equal(faqSchemaAnswer(plain), plain.paragraphs.join(' '))
  })
})

describe('the page renders it', () => {
  const page = () => read(PAGE)

  it('sits below the closing CTA, last before the footer', () => {
    // The CTA completes the creator journey; the FAQ is reference
    // material for somebody who wants to keep reading. It shipped
    // between World Builders and the CTA first, which made the page
    // ask its question and then keep talking.
    const src = page()
    const wb = src.indexOf('<WorldBuildersSection')
    const closing = src.indexOf('<ClosingInvitation')
    const faq = src.indexOf('<FaqSection')
    assert.ok(wb > 0 && closing > wb && faq > closing,
      'order must be World Builders → Closing → FAQ')
  })

  it('the closing CTA itself is untouched', () => {
    const src = page()
    assert.ok(src.includes("headingLines={['Ready to build your Collective?']}"))
    assert.ok(src.includes("primaryCta={{ label: 'Choose your plan', href: '/for-creators#plans' }}"))
  })

  it('anchors as #faq', () => {
    assert.match(page(), /<section id="faq"/)
  })

  it('carries the approved heading and introduction', () => {
    const src = page()
    assert.ok(src.includes('Questions creators ask'))
    assert.ok(src.includes('The practical bits, answered plainly.'))
  })

  it('uses a native disclosure, not a scripted one', () => {
    // Keyboard accessible and works without JavaScript, which a
    // hand-rolled disclosure does not get for free.
    const src = page()
    assert.match(src, /<details/)
    assert.match(src, /<summary/)
    assert.ok(!src.includes("'use client'"), 'the page stays a server component')
    assert.ok(!/useState|onClick=\{/.test(src), 'no client state driving the accordion')
  })

  it('reads its copy and schema from the shared module', () => {
    const src = page()
    assert.match(src, /from '@\/lib\/creatorFaq'/)
    assert.match(src, /CREATOR_FAQ\.map/)
    assert.match(src, /creatorFaqJsonLd\(\)/)
  })

  it('keeps the fee table from widening the page', () => {
    const src = page()
    const at = src.indexOf('function FeeTable')
    assert.ok(at > 0)
    const fn = src.slice(at, at + 2200)
    assert.match(fn, /overflow-x-auto/)
    assert.match(fn, /min-w-\[/)
  })

  it('hints that the fee table swipes, on phones only', () => {
    // The scroll is correct and invisible: the third column sits just
    // past the right edge with nothing to say it is there. On a wider
    // screen all three columns already show, so the hint would be
    // telling the reader to do something pointless.
    const src = page()
    const at = src.indexOf('function FeeTable')
    const fn = src.slice(at, at + 2200)
    assert.ok(fn.includes('Swipe to compare plans'), 'the hint exists')
    const hintAt = fn.indexOf('Swipe to compare plans')
    const el = fn.slice(Math.max(0, hintAt - 320), hintAt)
    assert.match(el, /sm:hidden/, 'mobile only')
    assert.match(el, /aria-hidden="true"/, 'not announced — nobody swipes a screen reader')
    assert.match(el, /INK_SOFT/, 'existing muted token, no new colour')
    // Above the scroll container, not inside it — otherwise it would
    // scroll away with the table.
    assert.ok(hintAt < fn.indexOf('overflow-x-auto'), 'sits above the table')
  })

  it('links the policies and the contact address', () => {
    const src = page()
    assert.match(src, /mailto:\$\{CONTACT_INFO_EMAIL\}/)
    assert.equal(CONTACT_INFO_EMAIL, 'info@freshcollective.au')
    assert.ok(src.includes('/world-guide/creator-agreement'))
    assert.ok(src.includes('/world-guide/payment-refund-and-cancellation-policy'))
  })

  it('leaves the rest of the page alone', () => {
    // The brief: no other copy, prices or sections change. These are the
    // landmarks that would move if something had.
    const src = page()
    for (const landmark of [
      'Ready to build your Collective?',
      'Choose the plan that matches what you',
      'World Builders Collective',
      'PROCESSING_COVERED_LINE',
      'PUBLIC_PLANS',
    ]) {
      assert.ok(src.includes(landmark), landmark)
    }
  })

  it('hard-codes no plan price outside the approved FAQ copy', () => {
    // The plans section reads prices from the shared config and must
    // keep doing so.
    const src = page()
    assert.ok(!/priceLabel: '\$/.test(src), 'no inline price labels')
    // The plans section still reads names, prices and CTAs from the
    // shared config rather than restating them.
    assert.match(src, /PUBLIC_PLANS\.community\.displayName/)
    assert.match(src, /PUBLIC_PLANS\.creator\.displayName/)
    assert.match(src, /PUBLIC_PLANS\.pro\.displayName/)
  })
})
