import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Stage 3D — one Ways to join section on the standalone Gathering
 * page, in the Collective's own colours.
 *
 * Two issues, both presentation. The buttons went teal because the
 * page never passed its palette to the shared purchase components —
 * they take it as a prop, and the Pathway page has always supplied
 * one. And the ticket sat under "Ticket" with the Options under
 * "Other ways to join" below a divider, which said the first was the
 * way in and the rest were alternatives.
 *
 * Source contracts, for the reason the sibling files give: these are
 * React components and the harness is node:test with no DOM. Nothing
 * here touches checkout — the identifiers each button sends are
 * pinned by `stage2cWaysToJoin.test.ts` and the backend suites.
 */

const SRC = join(process.cwd(), 'src')
const EVENT_PAGE = join(SRC, 'app', 'spaces', '[slug]', 'events', '[eventId]', 'page.tsx')
const WTJ = join(SRC, 'components', 'commerce', 'PathwayWaysToJoin.tsx')
const TICKET = join(SRC, 'components', 'spaces', 'GatheringTicketPurchaseClient.tsx')
const PATHWAY_ABOUT = join(SRC, 'app', 'spaces', '[slug]', 'pathways', '[pathway-slug]', 'about', 'page.tsx')
const SERIES_SIDEBAR = join(SRC, 'app', 'spaces', '[slug]', 'gathering-series', '[series-slug]', 'SeriesSidebar.tsx')

const read = (p: string) => readFileSync(p, 'utf8')
const code = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '')

describe('Issue A — Collective colours on every purchase button', () => {
  it('the Gathering page passes its palette to the shared components', () => {
    // The whole of the bug: the prop was dropped, so
    // `paletteHex('primary', null)` fell back to the platform teal
    // while the ticket button beside it used the Collective's colour.
    const src = code(EVENT_PAGE)
    const i = src.indexOf('<PathwayWaysToJoin')
    assert.ok(i > -1, 'the Gathering page no longer renders Ways to join')
    const block = src.slice(i, src.indexOf('/>', i))
    assert.match(block, /palette=\{palette\}/)
  })

  it('and the palette it passes is the Collective’s own', () => {
    const src = code(EVENT_PAGE)
    assert.match(src, /const palette: CollectivePaletteMeta \| null = space\?\.colour_palette/)
  })

  it('the ticket card is branded from the same palette', () => {
    const src = code(EVENT_PAGE)
    assert.match(src, /<WaysToJoinCard title="Individual ticket" palette=\{palette\}>/)
  })

  it('no Collective colour is hardcoded on this page', () => {
    // It must work for any Collective, not the one it was tested on.
    const src = code(EVENT_PAGE)
    assert.ok(!/Moonlit/i.test(src), 'a particular Collective is named')
  })

  it('the shared components still fall back only when there is no palette', () => {
    // The fallback stays — a Collective without a palette must still
    // get a readable button — but it is a fallback, not the default.
    const src = code(WTJ)
    assert.match(src, /paletteHex\('primary', palette \?\? null\) \?\? '#0f766e'/)
  })

  it('the ticket component keeps its own themed states', () => {
    // It reads CSS variables rather than a prop, and those states —
    // hover, loading, sold out, confirmed, pending — are untouched.
    const src = code(TICKET)
    assert.match(src, /var\(--fc-accent/)
    assert.match(src, /animate-spin/)
    assert.match(src, /Sold out/)
    assert.match(src, /cursor-not-allowed/)
  })
})

describe('Issue B — one Ways to join section, not a ticket and an aside', () => {
  it('the heading is unified when Options sit beside the ticket', () => {
    const src = code(EVENT_PAGE)
    assert.match(src, /hasPaymentOptionWays/)
    assert.match(src, /'Ways to join'/)
  })

  it('and the "Other ways to join" sub-heading is gone', () => {
    const src = read(EVENT_PAGE)
    assert.ok(
      !/Other ways to join/.test(src),
      'the Options are still presented as an afterthought',
    )
  })

  it('the Options list renders without a second heading', () => {
    const src = code(EVENT_PAGE)
    const i = src.indexOf('<PathwayWaysToJoin')
    const block = src.slice(i, src.indexOf('/>', i))
    assert.match(block, /showHeading=\{false\}/)
  })

  it('and the divider that separated them is gone', () => {
    const src = code(EVENT_PAGE)
    assert.ok(
      !/border-t border-slate-200 pt-5/.test(src),
      'a rule still divides the ticket from the Options',
    )
  })

  it('the ticket becomes a card of equal weight', () => {
    const src = code(EVENT_PAGE)
    assert.match(src, /<WaysToJoinCard title="Individual ticket"/)
  })

  it('nothing is labelled preferred or recommended', () => {
    const src = code(EVENT_PAGE)
    for (const w of ['Recommended', 'recommended', 'Best value', 'Most popular']) {
      assert.ok(!src.includes(w), `the panel promotes one arrangement: ${w}`)
    }
  })

  it('the unified layout only applies when there is something to unify', () => {
    // With no Payment Options the panel is exactly what it was:
    // "Ticket" over the ticket, every state unchanged.
    const src = code(EVENT_PAGE)
    const i = src.indexOf('const hasPaymentOptionWays')
    const decl = src.slice(i, src.indexOf('\n\n', i))
    assert.match(decl, /payment_option_ways_to_join/)
    assert.match(decl, /!isPast/)
    assert.match(decl, /!isCancelled/)
    assert.match(src, /'Ticket'/, 'the single-arrangement heading was removed')
  })
})

describe('Gathering-specific information survives', () => {
  it('capacity and remaining places still come from the ticket client', () => {
    const src = code(TICKET)
    assert.match(src, /spotsRemaining/)
    assert.match(src, /No capacity limit/)
    assert.match(src, /remaining/)
  })

  it('an existing booking still shows its own state', () => {
    const src = code(TICKET)
    assert.match(src, /Ticket purchased/)
    assert.match(src, /isConfirmed/)
  })

  it('and the ticket client is passed the same props as before', () => {
    // The frame changed; the inputs did not.
    const src = code(EVENT_PAGE)
    for (const prop of [
      'priceCents=', 'currency=', 'salesEnabled=', 'initialMyBookingStatus=',
      'spotsRemaining=', 'capacity=', 'isPast=', 'isCancelled=',
    ]) {
      assert.ok(src.includes(prop), `the ticket lost ${prop}`)
    }
  })
})

describe('nothing else moved', () => {
  it('the Pathway page is unchanged in how it renders Ways to join', () => {
    const src = code(PATHWAY_ABOUT)
    assert.match(src, /<PathwayWaysToJoin/)
    assert.match(src, /palette=\{collectivePalette\}/)
    assert.ok(
      !/showHeading/.test(src),
      'the Pathway page lost its own heading',
    )
  })

  it('the Gathering Series sidebar is untouched', () => {
    const src = code(SERIES_SIDEBAR)
    assert.match(src, /function CompactOptionCard/)
    assert.match(src, /Ways to join/)
    assert.ok(!/PathwayWaysToJoin/.test(src))
  })

  it('no checkout implementation was added', () => {
    // The page renders existing clients and passes identifiers; it
    // calculates nothing and calls nothing.
    const src = code(EVENT_PAGE)
    assert.ok(!/apiUrl\(/.test(src), 'the page calls the API directly')
    assert.ok(!/payment_option_schedule_id:/.test(src))
    assert.ok(!/unit_amount/.test(src))
  })
})
