import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Stage 3F — navigation and wording that said less than it knew.
 *
 * The behaviour behind each of these was already correct; what was
 * wrong was what members were told about it. Source contracts, for
 * the reason the sibling files give: these are React components and
 * the harness is node:test with no DOM.
 */

const SRC = join(process.cwd(), 'src')
const CONF = join(SRC, 'components', 'commerce', 'PurchaseConfirmation.tsx')
const ROW = join(SRC, 'components', 'activity', 'RecentMomentsRow.tsx')
const ROUTES = join(SRC, 'lib', 'routes.ts')
const EVENT_FORM = join(SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'EventForm.tsx')

const read = (p: string) => readFileSync(p, 'utf8')
const code = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '')

describe('Issue A — Your World is a title, /dashboard is the route', () => {
  it('the path is named once', () => {
    assert.match(code(ROUTES), /export const DASHBOARD_PATH = '\/dashboard'/)
  })

  it('the confirmation uses it rather than a literal', () => {
    const src = code(CONF)
    assert.match(src, /href=\{DASHBOARD_PATH\}/)
  })

  it('and the route that never existed is gone', () => {
    // `/your-world` was never a page. It read like one because the
    // dashboard is titled "Your World".
    for (const f of [CONF, ROW]) {
      assert.ok(
        !/\/your-world/.test(code(f)),
        `${f} still links to /your-world`,
      )
    }
  })
})

describe('Issue B — Recent Moments says what happened', () => {
  it('each supported event has its own phrasing', () => {
    const src = code(ROW)
    assert.match(src, /const EVENT_PHRASING/)
    for (const t of [
      'pathway_published', 'gathering_created', 'gathering_booking',
      'purchase_fulfilled', 'conversation_created',
    ]) {
      assert.ok(src.includes(t), `no phrasing for ${t}`)
    }
  })

  it('a publication reads as a publication', () => {
    assert.match(read(ROW), /New Pathway: \$\{n\}/)
    assert.match(read(ROW), /New Gathering: \$\{n\}/)
  })

  it('a purchase reads as joining', () => {
    assert.match(read(ROW), /You've joined \$\{n\}/)
  })

  it('a booking reads as being booked', () => {
    assert.match(read(ROW), /You're booked for \$\{n\}/)
  })

  it('an unknown event type is left exactly as it was', () => {
    // Presentation only: no record changes, and anything without an
    // entry renders the way it always did.
    const src = code(ROW)
    assert.match(src, /return phrase \? phrase\(t\.trim\(\)\) : t/)
  })

  it('a bundle says what came with it, in one row', () => {
    // One entry per purchase is the rule; the contents go in a
    // subtitle rather than in more rows.
    const src = code(ROW)
    assert.match(src, /function subtitleFor/)
    assert.match(src, /event_type !== 'purchase_fulfilled'/)
    assert.match(read(ROW), /Includes \$\{parts\.join/)
  })
})

describe('Issue F — what Require booking actually does', () => {
  it('explains the off state, which is the one that confused', () => {
    const src = read(EVENT_FORM)
    assert.match(src, /eligible members can simply turn up/)
    assert.match(src, /no place to reserve/)
  })

  it('and says a Series pass is not a booking', () => {
    const src = read(EVENT_FORM)
    assert.match(src, /A\s*\n?\s*Series pass lets a member attend eligible sessions/)
    assert.match(src, /reserve each\s*\n?\s*session individually/)
  })

  it('only when the Gathering is in a Series', () => {
    assert.match(code(EVENT_FORM), /\{Boolean\(seriesId\) && \(/)
  })

  it('and only while the setting is off', () => {
    const src = code(EVENT_FORM)
    assert.match(src, /\{!requiresBooking && !bookingRequiredByRules && \(/)
  })

  it('the toggle itself is untouched', () => {
    // §14: explain it, do not change it.
    const src = code(EVENT_FORM)
    assert.match(src, /checked=\{requiresBooking\}/)
    assert.match(src, /if \(bookingRequiredByRules\) return/)
    assert.match(src, /disabled=\{bookingRequiredByRules\}/)
  })
})
