import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Stage 3 activation — the two things the creator interface got wrong
 * once the feature was actually switched on.
 *
 * Both were the same mistake in different places: a frontend deciding
 * for itself what the backend is capable of. One hardcoded the answer,
 * the other inferred it from missing data. Neither asked.
 *
 * Source contracts, for the reason the sibling files give: these are
 * React components and the harness is node:test with no DOM. The
 * runtime capability itself is pinned in
 * `backend/tests/test_standalone_gathering_payment_options.py`.
 */

const SRC = join(process.cwd(), 'src')
const EVENT_FORM = join(SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'EventForm.tsx')
const PICKER = join(SRC, 'app', 'creator-studio', 'payment-options', '[optionId]', 'ExperiencePickerModal.tsx')
const PO_EDITOR = join(SRC, 'app', 'creator-studio', 'payment-options', '[optionId]', 'PaymentOptionEditorClient.tsx')

const read = (p: string) => readFileSync(p, 'utf8')
const code = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')

describe('Issue 1 — "ticket sales are switched off" when they are not', () => {
  it('the warning needs the backend to actually say sales are off', () => {
    // The reported bug. `ticket_sales` is a summary of a *saved*
    // Gathering, so while one is being created there is none — and
    // `?? false` turned "we don't know yet" into "switched off",
    // which is a different statement and was untrue in production.
    const src = code(EVENT_FORM)
    const i = src.indexOf('const salesExplicitlyOff')
    assert.ok(i > -1, 'the unknown case is still conflated with off')
    const decl = src.slice(i, src.indexOf('\n', i))
    assert.match(decl, /salesKnown/)
    assert.match(decl, /!salesEnabled/)
  })

  it('and the warning renders only on that condition', () => {
    const src = code(EVENT_FORM)
    assert.match(src, /\{salesExplicitlyOff && \(/)
    assert.ok(
      !/\{!salesEnabled && \(/.test(src),
      'the warning still fires whenever sales are merely unknown',
    )
  })

  it('"unknown" comes from there being no saved Gathering yet', () => {
    const src = code(EVENT_FORM)
    assert.match(src, /const salesKnown = ticketSales != null/)
  })

  it('the Payment Option guidance follows the real capability', () => {
    // The nearby copy said Payment Options cover "Pathways and
    // Gathering Series today" and that individual Gatherings were
    // coming. True until Stage 3 shipped; still displayed after.
    const src = code(EVENT_FORM)
    assert.match(src, /paymentOptionGatheringsEnabled/)
    assert.match(src, /ticketSales\?\.payment_option_gatherings_enabled/)
  })

  it('and both branches of that copy exist', () => {
    const src = read(EVENT_FORM)
    assert.match(src, /covers Pathways and Gathering\s+Series today/)
    assert.match(src, /a Payment Option can also include it/)
  })

  it('the capability is read from the backend, never derived here', () => {
    // The rule that stops this recurring: no component decides what
    // the server can do. There is no env var and no literal.
    const src = code(EVENT_FORM)
    assert.ok(
      !/STANDALONE_GATHERING/.test(src),
      'the editor reads a feature flag directly',
    )
    assert.ok(
      !/process\.env/.test(src),
      'the editor depends on a build-time variable',
    )
  })
})

describe('Issue 2 — Gatherings disabled in the Payment Option picker', () => {
  it('the picker asks rather than assuming', () => {
    // It read `kind === 'gathering'` outright. That was true when
    // standalone Gathering fulfilment did not exist, and stayed true
    // after it did — the feature shipped, the flag went on, and the
    // picker went on refusing because nothing here ever asked.
    const src = code(PICKER)
    const i = src.indexOf('const kindUnsupported')
    assert.ok(i > -1)
    const decl = src.slice(i, src.indexOf('\n', i))
    assert.match(decl, /kind === 'gathering'/)
    assert.match(decl, /!gatheringsEnabled/)
  })

  it('the capability arrives as a prop from the option payload', () => {
    const picker = code(PICKER)
    assert.match(picker, /gatheringsEnabled/)
    const editor = code(PO_EDITOR)
    assert.match(
      editor,
      /gatheringsEnabled=\{\s*option\.standalone_gathering_payment_options_enabled === true/,
    )
  })

  it('and defaults to refusing when the payload predates the field', () => {
    // An older payload must not unlock something checkout would
    // refuse. Absent means no.
    const src = code(PICKER)
    assert.match(src, /gatheringsEnabled = false/)
  })

  it('the coming-soon copy is conditional, not fixed', () => {
    const src = code(PICKER)
    assert.match(src, /\{kindUnsupported && \(/)
    assert.match(src, /kind === 'gathering' && gatheringsEnabled && \(/)
  })

  it('and when enabled the copy says what including one does', () => {
    const src = read(PICKER)
    assert.match(src, /books the member in when they/)
    assert.match(src, /can&rsquo;t be purchased until a place opens/)
  })

  it('Series and Pathways are unaffected either way', () => {
    // The gate names Gatherings specifically; nothing else changed.
    const src = code(PICKER)
    const i = src.indexOf('const kindUnsupported')
    const decl = src.slice(i, src.indexOf('\n', i))
    assert.ok(!/event_series/.test(decl))
    assert.ok(!/pathway/.test(decl))
  })
})
