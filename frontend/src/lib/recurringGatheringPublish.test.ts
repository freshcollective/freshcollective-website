import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * FC-209 — what the Gathering editor promises when you publish a run.
 *
 * The button said **Publish Series**, which told a creator they were
 * publishing a formal Gathering Series. They were not: a recurrence is
 * a run of independent Gatherings sharing a `recurrence_series_id`,
 * each booked and paid for separately. And because the editor read the
 * label as literally true, it hid the "Notify Collective members"
 * toggle — "the Series announces itself once" — which was only true
 * when the creator had also attached the batch to a real Series.
 * Without one, publishing twelve Gatherings told nobody at all.
 *
 * Asserted against the source because the form is a React component
 * and this harness is node:test with no DOM — the same approach, and
 * the same rationale, as `gatheringPublicLocation.test.ts` beside it.
 *
 * Comments are stripped before any absence check. A blunt
 * `includes()` over the whole file would be satisfied — or broken — by
 * a doc comment that merely *mentions* the old wording, which is
 * exactly the trap these source-contract tests keep falling into. The
 * rule is: ban the use, not the word.
 */

const FORM = join(
  process.cwd(), 'src', 'app', 'creator', 'spaces', '[slug]', 'events',
  'EventForm.tsx',
)

/** Source with `//` and block comments removed, so an absence check
 *  reads the code rather than the prose around it. */
function code(): string {
  return readFileSync(FORM, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

const raw = () => readFileSync(FORM, 'utf8')

describe('the publish button names what it does', () => {
  it('a recurring run publishes Recurring Gatherings', () => {
    assert.match(raw(), /'Publish Recurring Gatherings'/)
  })

  it('a single Gathering still publishes a Gathering', () => {
    assert.match(raw(), /'Publish Gathering'/)
  })

  it('nothing in the code still says Publish Series', () => {
    // A recurrence is not a formal Series, and the button must not
    // claim otherwise. Checked against comment-stripped source.
    assert.ok(
      !code().includes('Publish Series'),
      'the editor still offers "Publish Series" for a recurrence',
    )
  })
})

describe('the notify choice is offered for a recurring run', () => {
  it('the toggle is no longer hidden behind !isRecurring', () => {
    // The specific regression: `{!isRecurring && (` wrapped the
    // notify block, so a creator publishing a schedule was never
    // asked and never told.
    const src = code()
    const publication = src.slice(src.indexOf('PUBLICATION'))
    assert.ok(
      !publication.includes('{!isRecurring && ('),
      'the notify toggle is hidden again for recurring Gatherings',
    )
  })

  it('it says one email covers the whole schedule', () => {
    // The fear the hidden toggle was protecting against was twelve
    // emails. The copy has to answer it, or a creator will leave the
    // toggle off out of caution.
    const src = raw()
    assert.match(src, /about the whole schedule/)
    assert.match(src, /never one per date/)
  })

  it('it names the plural when the run is recurring', () => {
    assert.match(src_notify(), /about these Gatherings/)
    assert.match(src_notify(), /about this Gathering/)
  })

  it('it explains that a Series takes over when one is attached', () => {
    // Scenario B made visible: with a `series_id` the recurrence is
    // deliberately silent, and a creator should not be left wondering
    // why their schedule sent nothing.
    assert.match(src_notify(), /the Series\s*\n?\s*sends the announcement/)
  })
})

function src_notify(): string {
  const src = raw()
  return src.slice(src.indexOf('PUBLICATION'))
}

describe('the schedule is described as a schedule, not a Series', () => {
  it('the toggle invites repeating on a schedule', () => {
    assert.match(raw(), /Repeat on a schedule/)
  })

  it('it says each date is booked separately', () => {
    // The same promise the announcement email makes, made at the
    // point the creator decides.
    assert.match(raw(), /each booked separately/)
  })

  it('it says plainly that this is not a Gathering Series', () => {
    assert.match(raw(), /Not a\s*\n?\s*Gathering Series/)
  })

  it('the label field is a Schedule name', () => {
    assert.match(raw(), /Schedule name/)
    assert.ok(
      !code().includes('Series name'),
      'the recurrence label is still called "Series name"',
    )
  })
})
