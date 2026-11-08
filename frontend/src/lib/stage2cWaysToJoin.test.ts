import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Stage 2C — the Pathway Ways to join presentation.
 *
 * These are source contracts, for the reason the sibling Stage 0 and
 * Stage 2B files give: these are server/client React components and
 * the harness is node:test with no DOM. So they assert the things that
 * are decidable from source — which structure is shared, which
 * identifiers each button carries, that no single headline price is
 * constructed — and they cannot assert what a browser does with the
 * result. Layout at real widths was checked by hand; that is stated in
 * the report rather than implied here.
 *
 * The prices, ordering and availability behind the cards are pinned in
 * `backend/tests/test_pathway_ways_to_join.py`, and what the till
 * charges in `test_pathway_simultaneous_purchasing.py`.
 */

const SRC = join(process.cwd(), 'src')
const WTJ = join(SRC, 'components', 'commerce', 'PathwayWaysToJoin.tsx')
const ABOUT = join(SRC, 'app', 'spaces', '[slug]', 'pathways', '[pathway-slug]', 'about', 'page.tsx')
const CHECKOUT = join(SRC, 'app', 'spaces', '[slug]', 'pathways', '[pathway-slug]', 'checkout', 'page.tsx')
const SERIES_SIDEBAR = join(SRC, 'app', 'spaces', '[slug]', 'gathering-series', '[series-slug]', 'SeriesSidebar.tsx')
const SCHEDULE_CHOICE = join(SRC, 'components', 'commerce', 'ScheduleChoice.tsx')

const read = (p: string) => readFileSync(p, 'utf8')
const code = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')

describe('neither arrangement is the default', () => {
  it('both card kinds share one container', () => {
    // The structural half of equal treatment. Stage 3D took this
    // further: the container is now a single exported component that
    // both cards render, rather than two copies of the same markup,
    // so they cannot drift into a primary and a secondary card even
    // by accident.
    const src = code(WTJ)
    assert.match(src, /export function WaysToJoinCard/)
    assert.match(src, /rounded-2xl border p-4/)
    assert.match(src, /style=\{cardStyle\(primary\)\}/)
    // And exactly one definition of each.
    assert.equal(src.split('rounded-2xl border p-4').length - 1, 1)

    const direct = src.slice(src.indexOf('function DirectCard'), src.indexOf('function OptionCard'))
    const option = src.slice(src.indexOf('function OptionCard'))
    for (const [name, body] of [['direct', direct], ['option', option]] as const) {
      assert.match(body, /<WaysToJoinCard/, `${name} card uses the shared container`)
      assert.match(body, /palette=\{palette\}/, `${name} card is branded`)
    }
  })

  it('both buttons use the same appearance', () => {
    // `PurchaseScheduleButton` is rounded-xl in the Collective's
    // primary. The direct button opts into the same treatment rather
    // than keeping the platform gradient pill, which is what made the
    // two look like a primary and a secondary action.
    const src = code(WTJ)
    assert.match(src, /appearance="card"/)
    assert.match(src, /accentHex=\{accentHex\}/)
  })

  it('nothing is labelled recommended or best value', () => {
    // Comment-stripped: the component's own docstring explains this
    // rule, and a raw search finds the explanation. Ban the use, not
    // the word.
    const src = code(WTJ)
    for (const word of ['Recommended', 'recommended', 'Best value', 'Most popular']) {
      assert.ok(!src.includes(word), `the cards promote one option: ${word}`)
    }
  })

  it('the order is the backend list, never re-sorted', () => {
    // Ordering is the resolver's — direct first, then the creator's
    // own Option position. A sort here would quietly become a
    // recommendation algorithm.
    const src = code(WTJ)
    assert.match(src, /arrangements\.map\(/)
    assert.ok(
      !/\.sort\(/.test(src),
      'Ways to join re-sorts the arrangements',
    )
  })
})

describe('no single headline price', () => {
  it('the component builds no "from" amount', () => {
    const src = read(WTJ)
    assert.ok(!/\bFrom \$/.test(src))
    assert.ok(!/`From /.test(src))
  })

  it('the About page stops leading with one price when there are cards', () => {
    // The headline and the "See ways to join" hop are suppressed
    // together: the cards carry both the amounts and the actions.
    const src = code(ABOUT)
    assert.match(src, /const showWaysToJoin/)
    assert.match(src, /\{!showWaysToJoin && pathway\.member_plan_state\?\.status !== 'suspended' && \(/)
  })
})

describe('each button carries its own arrangement identity', () => {
  it('the direct card sends no Payment Option identifiers', () => {
    const src = code(WTJ)
    const direct = src.slice(src.indexOf('function DirectCard'), src.indexOf('function OptionCard'))
    assert.match(direct, /<CheckoutButton/)
    assert.match(direct, /pathwayId=\{pathwayId\}/)
    assert.ok(
      !/paymentOptionId/.test(direct),
      'the direct card can name a Payment Option',
    )
  })

  it('the Option card sends both Option and schedule identifiers', () => {
    const src = code(WTJ)
    const option = src.slice(src.indexOf('function OptionCard'))
    assert.match(option, /<ScheduleChoice/)
    assert.match(option, /paymentOptionId=\{arrangement\.payment_option_id/)
    // ScheduleChoice passes schedule.id through to the button; the
    // card must not substitute one schedule for another.
    assert.match(option, /schedule=\{s\}/)
    assert.match(option, /arrangement\.schedules\.map/)
  })

  it('every schedule gets its own action', () => {
    // Not one button for the Option with a radio group above it — the
    // pattern the Series established and the thing that makes
    // "silently select another schedule" inexpressible.
    const choice = code(SCHEDULE_CHOICE)
    assert.match(choice, /paymentOptionScheduleId=\{schedule\.id\}/)
  })
})

describe('what a bundle grants is stated', () => {
  it('the card names the other experiences', () => {
    const src = read(WTJ)
    assert.match(src, /Also includes/)
  })

  it('the viewed Pathway is dropped from that line, not the rest', () => {
    // included_titles leads with the Pathway being viewed, which is
    // implicit in context; slicing from 1 prints what *else* comes
    // with it. Printing nothing would imply a bundle grants only this
    // Pathway.
    const src = code(WTJ)
    assert.match(src, /included_titles\.slice\(1\)/)
  })

  it('a long list is counted rather than silently truncated', () => {
    const src = code(WTJ)
    assert.match(src, /slice\(0, 3\)/)
    assert.match(src, /and \$\{extra\} more/)
  })

  it('a direct purchase says it is this Pathway only', () => {
    assert.match(read(WTJ), /Access to this Pathway only/)
  })
})

describe('currency', () => {
  it('comes from the arrangement, never a literal', () => {
    const src = code(WTJ)
    assert.match(src, /formatMoneyCents\(arrangement\.price_cents, arrangement\.currency\)/)
    assert.ok(!/A\$/.test(src), 'a currency symbol is hardcoded')
    assert.ok(!/'AUD'/.test(src), 'AUD is hardcoded')
  })
})

describe('the Gathering Series is untouched', () => {
  it('still renders its own sidebar components', () => {
    // §2: the Series experience must remain visually and functionally
    // unchanged. It keeps its own card and its own copy; only the two
    // leaf components below it are shared.
    const src = code(SERIES_SIDEBAR)
    assert.match(src, /function CompactOptionCard/)
    assert.match(src, /Ways to join/)
    assert.ok(
      !/PathwayWaysToJoin/.test(src),
      'the Series page was rewired through the Pathway component',
    )
  })

  it('and the shared leaf components keep their Series behaviour', () => {
    // `ScheduleChoice` gained no Pathway-specific branch; the Pathway
    // card passes a different `ctaLabel`, which is a prop it already
    // had for exactly this.
    const src = code(SCHEDULE_CHOICE)
    assert.ok(!/pathway/i.test(src), 'ScheduleChoice learned about Pathways')
  })
})

describe('both Pathway surfaces render one implementation', () => {
  it('About and the selection page use the same component', () => {
    for (const f of [ABOUT, CHECKOUT]) {
      assert.match(code(f), /<PathwayWaysToJoin/)
    }
  })

  it('the selection page still exists and keeps its own states', () => {
    // §11: existing links and bookmarks must keep working, so the page
    // keeps its success/cancel handling and its already-have-access
    // branch. Only the discovery panel changed.
    const src = code(CHECKOUT)
    assert.match(src, /success/)
    assert.match(src, /user_has_access/)
  })

  it('and keeps a fallback for the deploy window', () => {
    // fc-web and fc-api deploy independently and in no guaranteed
    // order, so this page can briefly be served a payload with no
    // ways_to_join at all.
    const src = code(CHECKOUT)
    assert.match(src, /pathway\.ways_to_join \?\? \[\]/)
    assert.match(src, /PaymentOptionSelector/)
  })
})

describe('long content cannot push the page sideways', () => {
  it('a long Option name wraps', () => {
    // Now a property of the shared card's title, so it holds for the
    // Gathering page's individual-ticket card too.
    const src = code(WTJ)
    const card = src.slice(src.indexOf('export function WaysToJoinCard'))
    assert.match(card, /break-words/)
  })

  it('the cards are a single column with vertical spacing', () => {
    // Mobile is the stacked case by default: one column, gap between
    // cards, nothing horizontal to scroll.
    const src = code(WTJ)
    assert.match(src, /className="space-y-3"/)
    assert.ok(!/overflow-x/.test(src), 'a card scrolls sideways')
    assert.ok(!/whitespace-nowrap/.test(src), 'content is forced onto one line')
  })
})
