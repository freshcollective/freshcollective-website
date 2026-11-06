import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Stage 1B.1 — the preview is wired into both editors, and stays
 * read-only.
 *
 * Asserted against source for the reason the other creator-surface
 * tests give: these are React components and the harness is node:test
 * with no DOM. The *wording* and the *status logic* are tested as
 * values in `purchasePreview.test.ts`; this file covers the two
 * things only the surfaces can answer — that each editor renders the
 * section with the right experience, and that nothing in the preview
 * can write.
 *
 * Absence checks read comment-stripped source. Ban the use, not the
 * word: these files discuss writes, grants and checkout at length in
 * their own docstrings.
 */

const SRC = join(process.cwd(), 'src')
const COMPONENT = join(SRC, 'components', 'creator', 'PurchasePreviewSection.tsx')
const LIB = join(SRC, 'lib', 'purchasePreview.ts')
const PATHWAY_SETTINGS = join(
  SRC, 'app', 'creator-studio', 'pathways', '[pathwaySlug]', 'PathwaySettingsClient.tsx',
)
const EVENT_FORM = join(
  SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'EventForm.tsx',
)

const read = (p: string) => readFileSync(p, 'utf8')

/** Source with comments removed, so an absence check reads the code. */
function code(p: string): string {
  return read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

// ---------------------------------------------------------------------------

describe('the Pathway editor shows the preview', () => {
  it('renders the section for the Pathway being edited', () => {
    const src = read(PATHWAY_SETTINGS)
    assert.match(src, /<PurchasePreviewSection/)
    assert.match(src, /kind="pathway"/)
    assert.match(src, /experienceId=\{pathway\.id\}/)
  })

  it('under the agreed heading', () => {
    assert.match(
      read(PATHWAY_SETTINGS),
      /heading="How members can access this Pathway"/,
    )
  })

  it('for every access type, not only Payment Option access', () => {
    // The legacy directly-priced Pathway is exactly the case that
    // needed explaining, and the old reference block skipped it.
    const src = code(PATHWAY_SETTINGS)
    const i = src.indexOf('<PurchasePreviewSection')
    const before = src.slice(Math.max(0, i - 220), i)
    assert.ok(
      !before.includes("accessType === 'included_with_offer'"),
      'the preview is still gated on Payment Option access',
    )
  })

  it('and the superseded reference block is gone, not left beside it', () => {
    // Two adjacent sections both listing Payment Options is the
    // duplication this stage was told to avoid.
    const src = read(PATHWAY_SETTINGS)
    assert.ok(!src.includes('<PathwayPaymentOptionsReference'))
    assert.ok(!src.includes("from './PathwayPaymentOptionsReference'"))
  })

  it('without disturbing the unlock-set derivation', () => {
    // A separate reader of the same endpoint feeds save-time
    // validation. It is not part of the preview and must stay.
    const src = read(PATHWAY_SETTINGS)
    assert.match(src, /payment-option-references/)
    assert.match(src, /setUnlockOptionIds\(/)
  })

  it('and still refuses to write a paid access type', () => {
    // The Stage 0 protection. Untouched.
    const src = code(PATHWAY_SETTINGS)
    const i = src.indexOf('function handleChoiceClick')
    assert.ok(i > 0)
    assert.match(src.slice(i, i + 260), /setPricingMode\('legacy'\)/)
  })
})

describe('the Gathering editor shows the preview', () => {
  it('renders the section for the Gathering being edited', () => {
    const src = read(EVENT_FORM)
    assert.match(src, /<PurchasePreviewSection/)
    assert.match(src, /kind="gathering"/)
    assert.match(src, /experienceId=\{event\.id\}/)
  })

  it('only for a Gathering that already exists', () => {
    // A new Gathering has no row to resolve arrangements from.
    assert.match(read(EVENT_FORM), /\{event\?\.id && \(\s*<PurchasePreviewSection/)
  })

  it('under the agreed heading', () => {
    assert.match(
      read(EVENT_FORM),
      /heading="How members can book this Gathering"/,
    )
  })

  it('with helper text that does not promise Gathering Payment Options', () => {
    const src = read(EVENT_FORM)
    const i = src.indexOf('helperText=')
    const helper = src.slice(i, i + 320)
    assert.match(helper, /Payment Options cover Pathways and Gathering Series/)
    // Must not imply an individual Gathering can be bought through one.
    assert.ok(!/manage additional payment arrangements through Payment Options/i.test(helper))
  })

  it('and the existing ticket controls are untouched', () => {
    const src = read(EVENT_FORM)
    assert.match(src, /id="ticket-price"/)
    assert.match(src, /id="ticket-currency"/)
    assert.match(src, /setTicketPriceInput/)
    // The Stage 0 warning beside the price stays.
    assert.match(src, /Ticket sales are switched off on this environment/)
    assert.match(src, /a ticket price here is how a single Gathering is sold/)
  })
})

describe('the preview cannot write', () => {
  it('sends nothing but a GET', () => {
    const src = code(COMPONENT)
    assert.match(src, /\/purchase-preview\//)
    for (const verb of ['PATCH', 'POST', 'PUT', 'DELETE']) {
      assert.ok(!src.includes(`'${verb}'`), `the preview issues a ${verb}`)
      assert.ok(!src.includes(`"${verb}"`), `the preview issues a ${verb}`)
    }
    assert.ok(!/method:/.test(src), 'the preview sets a request method')
  })

  it('offers no control that edits', () => {
    const src = code(COMPONENT)
    for (const tag of ['<input', '<select', '<textarea', '<button', '<form']) {
      assert.ok(!src.includes(tag), `the preview renders ${tag}`)
    }
    assert.ok(!/onChange|onSubmit|onClick/.test(src), 'the preview has a handler')
  })

  it('and links out for every change instead', () => {
    const src = read(COMPONENT)
    // Per-Option, to that Option's editor.
    assert.match(src, /\/creator-studio\/payment-options\/\$\{group\.payment_option_id\}/)
    assert.match(src, /Edit this option/)
    // And a section-level route into Commerce.
    assert.match(src, /href="\/creator-studio\/payment-options"/)
    assert.match(src, /Manage Payment Options/)
  })
})

describe('nothing technical reaches the creator', () => {
  it('no database field names are rendered', () => {
    // Field names appear in the TypeScript interface and in property
    // reads, which is correct; what must never appear is one inside
    // rendered text. Checked on the text nodes of the component.
    const rendered = code(COMPONENT)
      .split('\n')
      .filter((l) => />[^<>{}]*[A-Za-z]{3}[^<>{}]*</.test(l))
      .join('\n')
    for (const leak of [
      'pricing_mode', 'price_cents', 'payment_option_id', 'grant_kind',
      'schedule_type', 'event_series', 'recurring_installments',
      'pay_in_full', 'paid_separately', 'included_with_offer',
    ]) {
      assert.ok(!rendered.includes(leak), `"${leak}" is rendered to the creator`)
    }
  })

  it('no Stripe object is referenced at all', () => {
    const src = code(COMPONENT) + code(LIB)
    assert.ok(!/stripe/i.test(src), 'the preview mentions Stripe')
    assert.ok(!/\bsub_|\bprice_1|\bcs_/.test(src))
  })

  it('a reason code is never shown raw', () => {
    // Every branch returns a sentence. The fallback is the guard, and
    // it must not interpolate the code.
    const lib = read(LIB)
    const i = lib.indexOf('default:')
    const fallback = lib.slice(i, i + 220)
    assert.ok(!fallback.includes('unavailable_reason'), fallback)
    assert.match(fallback, /Members cannot purchase/)
  })

  it('and an internal arrangement identifier is never requested', () => {
    // The API does not return one; the React key is built from what
    // the preview legitimately has.
    const src = code(COMPONENT) + code(LIB)
    assert.ok(!src.includes('arrangement_id'))
    assert.ok(!src.includes('payment_option_schedule_id'))
  })
})

describe('the layout survives a narrow screen', () => {
  it('every row wraps rather than overflowing', () => {
    const src = read(COMPONENT)
    const rows = src.match(/className="flex[^"]*"/g) ?? []
    assert.ok(rows.length >= 3, 'no flex rows found')
    for (const row of rows) {
      if (row.includes('justify-between')) {
        assert.ok(
          row.includes('flex-wrap'),
          `a justified row cannot wrap: ${row}`,
        )
      }
    }
  })

  it('the badge keeps its size and the text yields', () => {
    const src = read(COMPONENT)
    assert.match(src, /shrink-0/)
    assert.match(src, /min-w-0 flex-1/)
  })

  it('and nothing is pinned to a fixed pixel width', () => {
    const src = read(COMPONENT)
    // `max-w-[560px]` on the heading column is a ceiling, not a
    // fixed width — the class boundary has to be explicit or the
    // `\b` matches inside `max-w-`.
    assert.ok(!/(?:^|[\s"])w-\[\d+px\]/.test(src))
    // A max-width on the heading column is fine; a fixed width is not.
    assert.ok(!/\bwidth:\s*\d+px/.test(src))
  })
})
