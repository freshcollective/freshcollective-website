import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Creator Studio → Gatherings → Create Gathering → recurrence controls.
 *
 * A creator reported that there was "no visible option to enable
 * recurring scheduling at all" in Creator Studio. The controls were in
 * fact rendered, deployed and reachable — but nothing tested the
 * *chain*, so the report could not be answered from the test suite, and
 * two things had made the chain hard to walk:
 *
 *   1. FC-209 renamed the toggle from "Recurring series" to "Repeat on
 *      a schedule". Correct about Series, but it removed the word a
 *      creator searches for, and "Recurring" then appeared only on the
 *      submit button at the foot of the form.
 *
 *   2. The Gatherings page described a Gathering Series as a way to
 *      group "an ongoing circle" — which is precisely the recurrence
 *      use case — beside a prominent "New Series" button, while
 *      "Create Gathering" sat in the artwork header. A creator wanting
 *      a monthly circle was being pointed at the one flow that has no
 *      recurrence in it.
 *
 * So this file asserts the route, the component and the label, as one
 * chain. Each link is cheap; the chain is what was missing.
 *
 * Asserted against source, for the reason `gatheringPublicLocation.test.ts`
 * gives: these are React components and the harness is node:test with
 * no DOM. Absence checks read comment-stripped source — ban the use,
 * not the word.
 */

const SRC = join(process.cwd(), 'src')
const STUDIO = join(SRC, 'app', 'creator-studio', 'gatherings', 'page.tsx')
const BAND = join(
  SRC, 'app', 'creator-studio', 'gatherings', 'GatheringSeriesBand.tsx',
)
const NEW_PAGE = join(
  SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'new', 'page.tsx',
)
const FORM = join(
  SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'EventForm.tsx',
)

const read = (p: string) => readFileSync(p, 'utf8')

/** Source with comments removed, so an absence check reads the code. */
function code(p: string): string {
  return read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

describe('the route a creator actually takes', () => {
  it('Creator Studio → Gatherings offers Create Gathering', () => {
    const src = read(STUDIO)
    assert.match(src, /Create Gathering/)
    assert.match(src, /\/events\/new/)
  })

  it('that link lands on the shared Gathering editor', () => {
    // The one create route. If a second creation surface is ever added
    // it has to carry recurrence too, or this report recurs.
    assert.match(read(NEW_PAGE), /from '\.\.\/EventForm'/)
    assert.match(read(NEW_PAGE), /<EventForm/)
  })

  it('and renders it as a create, not an edit', () => {
    // `isEdit = !!event`, and the recurrence block is the one thing
    // gated on `!isEdit`. Passing an `event` here would hide it.
    const src = code(NEW_PAGE)
    const tag = src.slice(src.indexOf('<EventForm'), src.indexOf('/>', src.indexOf('<EventForm')))
    assert.ok(
      !/\bevent=/.test(tag),
      'new/page.tsx passes an `event` prop, which would hide the recurrence controls',
    )
  })

  it('the form keys recurrence off nothing but create-vs-edit', () => {
    // No Gathering type, no Series, no plan, no permission, no
    // breakpoint. If a second condition is ever added, this fails and
    // somebody has to say why a creator may not repeat a Gathering.
    const src = code(FORM)
    const i = src.indexOf('Recurring Gatherings</span>')
    assert.ok(i > 0, 'the recurrence toggle label is missing')
    const guard = src.slice(src.lastIndexOf('{!isEdit && (', i), i)
    assert.ok(
      guard.length > 0 && guard.length < 700,
      'the recurrence block is no longer directly inside the !isEdit guard',
    )
    assert.ok(
      !/isRecurring\s*&&/.test(guard),
      'the toggle itself is now behind isRecurring, so it can never be turned on',
    )
  })
})

describe('the control is findable by the name creators use', () => {
  it('the toggle says Recurring Gatherings', () => {
    // The regression FC-209 introduced: "Repeat on a schedule" is
    // accurate but contains neither "recurring" nor "repeat this
    // Gathering", so scanning the form for the feature failed.
    assert.match(read(FORM), /Recurring Gatherings<\/span>/)
  })

  it('and explains what it does without saying Series', () => {
    const src = read(FORM)
    assert.match(src, /Repeat this Gathering on a schedule/)
    assert.match(src, /one Gathering per\s*\n?\s*date/)
    assert.match(src, /booked and paid for separately/)
    assert.match(src, /not a Gathering\s*\n?\s*Series/)
  })

  it('the submit button still names the plural outcome', () => {
    assert.match(read(FORM), /'Publish Recurring Gatherings'/)
    assert.match(read(FORM), /'Publish Gathering'/)
  })
})

describe('the Gatherings page no longer points recurrence at Series', () => {
  it('the Series band stops claiming an ongoing circle', () => {
    // "an ongoing circle" is a recurrence use case. Offering it as the
    // reason to create a Series is what sent a creator looking for
    // recurrence into the one flow that has none.
    assert.ok(
      !code(BAND).includes('ongoing\n            circle'),
      'the Series band still offers itself for an ongoing circle',
    )
    assert.match(read(BAND), /connected experience/)
    assert.match(read(BAND), /bought as a whole/)
  })

  it('it points repeating Gatherings at Create Gathering instead', () => {
    const src = read(BAND)
    assert.match(src, /repeating the same Gathering on a schedule/)
    assert.match(src, /Create Gathering/)
    assert.match(src, /Recurring Gatherings/)
    assert.match(src, /no Series needed/)
  })

  it('the standalone empty state mentions a recurring run', () => {
    assert.match(read(STUDIO), /one date, or a recurring run/)
  })
})

describe('the four Gathering flows stay distinct', () => {
  it('one Gathering — the toggle off', () => {
    // Single creation posts to /events; the recurring branch posts to
    // /events/bulk. Both live in the same form behind the toggle.
    const src = read(FORM)
    assert.match(src, /if \(!isEdit && isRecurring\) \{/)
    assert.match(src, /\/events\/bulk/)
  })

  it('a formal Series is created from its own band, not the form', () => {
    // Creating a Series must not become a step on the way to a
    // recurring Gathering — the two are different products.
    assert.match(read(BAND), /New Series/)
    assert.match(read(BAND), /method: 'POST'/)
    assert.match(read(BAND), /gathering-series/)
  })

  it('adding a Gathering to an existing Series keeps its own entry', () => {
    const series = read(join(
      SRC, 'app', 'creator-studio', 'gathering-series', '[seriesSlug]',
      'SeriesEditorClient.tsx',
    ))
    assert.match(series, /\/events\/new\?series_id=/)
  })

  it('arriving from a Series preselects it without hiding recurrence', () => {
    // `initialSeriesId` seeds the Series picker only. A creator may
    // still generate a run of dates inside a Series — that is
    // supported, and the Series then owns the announcement.
    const form = code(FORM)
    assert.match(form, /initialSeriesId \?\? ''/)
    const i = form.indexOf('Recurring Gatherings</span>')
    const guard = form.slice(form.lastIndexOf('{!isEdit && (', i), i)
    assert.ok(
      !/seriesId/.test(guard),
      'recurrence is now hidden when a Series is preselected',
    )
  })
})

describe('both creation actions sit on their own section heading', () => {
  it('Create Gathering is no longer in the banner', () => {
    // It used to be a white-on-artwork link in the header while New
    // Series was a solid button in the body, so the less common action
    // was the louder one. Both now sit on the heading of the section
    // they create into.
    const src = code(STUDIO)
    const header = src.slice(
      src.indexOf('<CollectiveArtworkHeader'),
      src.indexOf('/>', src.indexOf('<CollectiveArtworkHeader')),
    )
    assert.ok(header.length > 0, 'the artwork header is gone')
    assert.ok(
      !header.includes('Create Gathering'),
      'Create Gathering is back in the banner',
    )
  })

  it('the banner keeps its archive link', () => {
    const src = code(STUDIO)
    const header = src.slice(
      src.indexOf('<CollectiveArtworkHeader'),
      src.indexOf('/>', src.indexOf('<CollectiveArtworkHeader')),
    )
    assert.match(header, /archiveLinkLabel/)
    assert.match(header, /gatherings\/archive/)
  })

  it('Create Gathering sits on the Standalone Gatherings heading', () => {
    const src = code(STUDIO)
    const i = src.indexOf('Standalone Gatherings')
    assert.ok(i > 0)
    // Within the heading row that follows, not somewhere further down
    // the page.
    const row = src.slice(i, i + 900)
    assert.match(row, /PrimaryActionLink/)
    assert.match(row, /Create Gathering/)
    assert.match(row, /\/events\/new/)
  })

  it('and is styled by the same component the Series button mirrors', () => {
    // PrimaryActionLink documents itself as mirroring Button
    // variant="primary" size="md" — which is exactly what New Series
    // renders — so the two match without either importing the other.
    const link = read(join(SRC, 'components', 'creator', 'PrimaryActionLink.tsx'))
    assert.match(link, /VARIANT\.primary/)
    assert.match(link, /SIZE\.md/)
    assert.match(link, /h-10 px-4 text-\[13px\] rounded-\[var\(--fc-radius-md\)\]/)

    const button = read(join(SRC, 'components', 'platform', 'Button.tsx'))
    assert.match(button, /md: 'h-10 px-4 text-\[13px\] rounded-\[var\(--fc-radius-md\)\]'/)
    assert.match(read(BAND), /<Button variant="primary"/)
  })

  it('the heading row wraps rather than squashing on a phone', () => {
    const src = code(STUDIO)
    const i = src.indexOf('Standalone Gatherings')
    const row = src.slice(Math.max(0, i - 300), i)
    assert.match(row, /flex flex-wrap items-start justify-between gap-3/)
  })

  it('it matches the Series heading row it sits beside', () => {
    // Same flex contract on both headings, so the two sections read as
    // a pair rather than two near-misses.
    assert.match(read(BAND), /flex flex-wrap items-start justify-between gap-3/)
  })

  it('the action is present even with no standalone Gatherings yet', () => {
    // The empty state is exactly when a creator needs the button, so
    // the heading must not be inside the `standalone.length > 0` branch.
    const src = code(STUDIO)
    const i = src.indexOf('Standalone Gatherings')
    const before = src.slice(Math.max(0, i - 400), i)
    assert.ok(
      !before.includes('standalone.length > 0'),
      'the heading and its button only render once a Gathering exists',
    )
  })
})
