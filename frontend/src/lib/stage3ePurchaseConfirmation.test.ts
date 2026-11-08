import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Stage 3E.3 — the purchase confirmation.
 *
 * A Payment Option can contain several experiences, and checkout
 * returns the member to whichever one they started from. That page can
 * only speak for itself, so buying a bundle of a Gathering and a
 * Pathway looked exactly like buying a ticket.
 *
 * Source contracts, for the reason the sibling files give: these are
 * React components and the harness is node:test with no DOM. The
 * behaviour that matters most — who may read a purchase, and what it
 * says about a refunded one — is asserted against the real endpoint in
 * `backend/tests/test_purchase_summary_endpoint.py`.
 */

const SRC = join(process.cwd(), 'src')
const CONF = join(SRC, 'components', 'commerce', 'PurchaseConfirmation.tsx')
const SCHEDULE_BTN = join(SRC, 'components', 'commerce', 'PurchaseScheduleButton.tsx')
const EVENT_PAGE = join(SRC, 'app', 'spaces', '[slug]', 'events', '[eventId]', 'page.tsx')
const PATHWAY_CHECKOUT = join(SRC, 'app', 'spaces', '[slug]', 'pathways', '[pathway-slug]', 'checkout', 'page.tsx')
const SERIES_PAGE = join(SRC, 'app', 'spaces', '[slug]', 'gathering-series', '[series-slug]', 'page.tsx')
const SERIES_SIDEBAR = join(SRC, 'app', 'spaces', '[slug]', 'gathering-series', '[series-slug]', 'SeriesSidebar.tsx')
const CHECKOUT_BTN = join(SRC, 'components', 'checkout', 'CheckoutButton.tsx')

const read = (p: string) => readFileSync(p, 'utf8')
const code = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '')

describe('the purchase is identified, not guessed', () => {
  it('the Option checkout brings its session id back', () => {
    // Stripe substitutes `{CHECKOUT_SESSION_ID}` at redirect. The same
    // convention CheckoutButton and AcquireOffering already use — this
    // path simply never carried one.
    const src = code(SCHEDULE_BTN)
    assert.match(src, /session_id=\{CHECKOUT_SESSION_ID\}/)
  })

  it('and the existing direct-purchase convention is untouched', () => {
    assert.match(code(CHECKOUT_BTN), /session_id=\{CHECKOUT_SESSION_ID\}/)
  })

  it('the component asks the backend rather than trusting the URL', () => {
    // `?checkout=success` is a trigger to ask a question, never its
    // answer: a member can reach that URL by pressing Back.
    const src = code(CONF)
    assert.match(src, /\/api\/checkout\/purchase-summary\?session_id=/)
    assert.match(src, /encodeURIComponent\(sessionId\)/)
    assert.match(src, /credentials: 'include'/)
  })

  it('and never decides a purchase succeeded on its own', () => {
    const src = code(CONF)
    // Every claim comes from `state`, which is the ledger's word —
    // destructured off the fetched summary, never read from the URL.
    assert.match(src, /const \{ state \} = summary/)
    assert.ok(
      !/searchParams\.get\('checkout'\)/.test(src),
      'the component reads success from the URL',
    )
  })
})

describe('it only ever reads', () => {
  it('issues no write of any kind', () => {
    const src = code(CONF)
    for (const verb of ['POST', 'PATCH', 'PUT', 'DELETE']) {
      assert.ok(!src.includes(`'${verb}'`), `the confirmation issues a ${verb}`)
    }
    assert.ok(!/method:/.test(src), 'the confirmation sets a request method')
  })

  it('and calculates no money', () => {
    // §9: every figure comes from the backend, which reads the
    // PurchasePlan. An email or a panel doing its own arithmetic is
    // one that can disagree with the ledger.
    const src = code(CONF)
    assert.ok(!/\*\s*summary\.installments/.test(src))
    assert.ok(!/installment_amount_cents\s*\*/.test(src))
  })
})

describe('the states it distinguishes', () => {
  it('pending and fulfilling are not success', () => {
    const src = code(CONF)
    assert.match(src, /state === 'pending'/)
    assert.match(src, /'fulfilling'/)
  })

  it('a failed payment shows no confirmation', () => {
    const src = read(CONF)
    assert.match(src, /didn&rsquo;t go through/)
    assert.match(src, /Nothing has been charged/)
  })

  it('a refunded purchase is distinguished from a new one', () => {
    const src = code(CONF)
    assert.match(src, /state === 'refunded'/)
    assert.match(src, /const refunded = state === 'refunded'/)
    assert.match(src, /refunded=\{refunded\}/)
  })

  it('an instalment is not described as paid in full', () => {
    const src = read(CONF)
    assert.match(src, /Payment plan established/)
    assert.match(src, /First payment/)
    assert.match(src, /remaining/)
  })
})

describe('polling is bounded and stops', () => {
  it('has a ceiling', () => {
    const src = code(CONF)
    assert.match(src, /const MAX_POLLS = \d+/)
    assert.match(src, /polls\.current >= MAX_POLLS/)
  })

  it('a timeout says still finalising, never failed', () => {
    const src = read(CONF)
    assert.match(src, /still being finalised/)
  })

  it('stops on a terminal state', () => {
    const src = code(CONF)
    assert.match(src, /state !== 'pending' && state !== 'fulfilling'/)
  })

  it('and makes no request after unmount', () => {
    const src = code(CONF)
    assert.match(src, /alive\.current = false/)
    assert.match(src, /clearTimeout\(timer\)/)
  })
})

describe('it is temporary and dismissible', () => {
  it('can be closed deliberately', () => {
    const src = code(CONF)
    assert.match(src, /setDismissed\(true\)/)
    assert.match(src, /if \(dismissed \|\| notFound\) return null/)
  })

  it('does not auto-dismiss a completed summary', () => {
    // §10: it must stay long enough to read.
    const src = code(CONF)
    assert.ok(
      !/setTimeout\(\s*\(\)\s*=>\s*setDismissed/.test(src),
      'the summary disappears on a timer',
    )
  })

  it('renders nothing at all when there is no purchase to show', () => {
    const src = code(CONF)
    assert.match(src, /if \(!summary\) return null/)
  })
})

describe('one component, a small integration per surface', () => {
  for (const [label, file] of [
    ['the Gathering page', EVENT_PAGE],
    ['the Pathway checkout page', PATHWAY_CHECKOUT],
    ['the Gathering Series page', SERIES_PAGE],
  ] as const) {
    it(`${label} renders it only when a session comes back`, () => {
      const src = code(file)
      assert.match(src, /<PurchaseConfirmation/)
      assert.match(src, /session_?[Ii]d/)
      assert.match(src, /palette=\{/)
    })
  }

  it('and neither page gained a permanent purchase panel', () => {
    // §10: the confirmation is specific to a completed purchase, not
    // part of the page.
    for (const file of [EVENT_PAGE, PATHWAY_CHECKOUT, SERIES_PAGE]) {
      const src = code(file)
      assert.match(src, /\{(purchaseSessionId|session_id) && \(/)
    }
  })

  it('the Series page keeps everything it already did', () => {
    // §9: the confirmation sits above the Series' own panels; it
    // replaces none of them.
    const src = code(SERIES_PAGE)
    assert.match(src, /<SidebarWaysToJoin/)
    assert.match(src, /<SidebarYourAccess/)
    assert.match(src, /justPurchased/)
  })

  it('and its Ways to join is untouched', () => {
    const src = code(SERIES_SIDEBAR)
    assert.match(src, /function CompactOptionCard/)
    assert.ok(!/PurchaseConfirmation/.test(src))
  })

  it('the Series return already carried a session id', () => {
    // No checkout routing changed for this: every Payment Option
    // checkout has appended one since 3E.3, this page included.
    const src = code(SCHEDULE_BTN)
    assert.match(src, /session_id=\{CHECKOUT_SESSION_ID\}/)
  })
})

describe('presentation', () => {
  it('uses the Collective palette, not a fixed colour', () => {
    const src = code(CONF)
    assert.match(src, /paletteHex\('primary', palette \?\? null\)/)
  })

  it('formats money with the shared helper', () => {
    const src = code(CONF)
    assert.match(src, /formatMoneyCents/)
    assert.ok(!/A\$/.test(src), 'a currency symbol is hardcoded')
  })

  it('announces itself to assistive technology', () => {
    const src = code(CONF)
    assert.match(src, /role="status"/)
    assert.match(src, /aria-live="polite"/)
    assert.match(src, /aria-label="Dismiss purchase confirmation"/)
  })

  it('long titles wrap rather than pushing the page sideways', () => {
    const src = code(CONF)
    assert.match(src, /break-words/)
    assert.ok(!/overflow-x/.test(src))
  })
})
