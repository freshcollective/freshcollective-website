import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * Public location is a field the editor both writes and reads back.
 *
 * A creator changed it on a published Gathering three times and the
 * old value kept returning. The cause was on the backend — the creator
 * detail payload omitted `venue_locality`, so the box loaded blank
 * however much the row held, and a save that left it alone sent null.
 *
 * The frontend side of that loop is asserted here because it is what
 * makes the field self-correcting: the input must be initialised from
 * the loaded Gathering, and the save must carry it. TypeScript could
 * not catch the original bug — `CreatorEvent` declared the field, so
 * the editor was right to read it and the server was simply not
 * sending it.
 *
 * Asserted against the source because the form is a React component
 * and this harness is node:test with no DOM. A shape check that fails
 * loudly on removal beats no check at all.
 */

const SRC = join(process.cwd(), 'src')
const FORM = join(
  SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'EventForm.tsx',
)
const TYPES = join(SRC, 'types', 'platform.ts')

const form = () => readFileSync(FORM, 'utf8')

describe('the Gathering editor round-trips Public location', () => {
  it('initialises the box from the loaded Gathering', () => {
    assert.ok(
      /useState\(event\?\.venue_locality \?\? ''\)/.test(form()),
      'the Public location input no longer loads from the saved Gathering',
    )
  })

  it('sends it on save', () => {
    assert.ok(
      /venue_locality: venueLocality \|\| null/.test(form()),
      'the save payload no longer carries venue_locality',
    )
  })

  it('binds the input to that state', () => {
    const source = form()
    const field = source.slice(source.indexOf('Public location'))
    assert.ok(
      /value=\{venueLocality\}/.test(field),
      'the Public location input is not bound to venueLocality',
    )
    assert.ok(
      /onChange=\{\(e\) => setVenueLocality\(e\.target\.value\)\}/.test(field),
      'typing in Public location no longer updates venueLocality',
    )
  })

  it('does not share state with venue name or address', () => {
    // The three live in one form section and the reporter noticed the
    // other two saving correctly, so a crossed setter was a live
    // hypothesis worth closing.
    const source = form()
    for (const [state, setter] of [
      ['venueLocality', 'setVenueLocality'],
      ['venueName', 'setVenueName'],
      ['venueAddress', 'setVenueAddress'],
    ]) {
      const declarations = source.split(`const [${state}, ${setter}]`).length - 1
      assert.equal(declarations, 1, `${state} is declared ${declarations} times`)
    }
  })

  it('an empty box is sent as null rather than omitted', () => {
    // The backend reads `model_fields_set`, so an explicit null clears
    // the field and omission preserves it. The editor must therefore
    // send the key every time — which `|| null` does.
    const source = form()
    const payload = source.slice(
      source.indexOf('const basePayload'),
      source.indexOf('if (!isEdit && isRecurring)'),
    )
    assert.ok(
      payload.includes('venue_locality'),
      'venue_locality left the save payload',
    )
  })
})

describe('the Gathering type declares the field', () => {
  it('CreatorEvent carries venue_locality', () => {
    // It always did, which is why type-check stayed silent while the
    // server sent nothing. Kept as a test so the editor's read has a
    // declared contract to point at.
    const types = readFileSync(TYPES, 'utf8')
    const block = types.slice(types.indexOf('export interface CreatorEvent'))
    const body = block.slice(0, block.indexOf('\n}'))
    assert.ok(
      /venue_locality: string \| null/.test(body),
      'CreatorEvent no longer declares venue_locality',
    )
  })
})

describe('Public location is the only location field shown publicly', () => {
  it('the venue address input still says attendees only', () => {
    // The privacy split must survive any edit to this section.
    const source = form()
    const section = source.slice(source.indexOf('Venue and attendee details'))
    assert.ok(
      /Only shared with people who are entitled to receive attendance/
        .test(section),
      'the attendee-only wording around the venue fields is gone',
    )
    assert.ok(
      /shown only to registered attendees/i.test(section),
      'the venue address no longer states who can see it',
    )
  })

  it('the Public location help text still warns against an address', () => {
    // Guidance, not a restriction: a creator may deliberately enter a
    // full address and the backend persists whatever they save.
    assert.ok(
      /Shown publicly so people know roughly where/.test(form()),
      'the Public location guidance is gone',
    )
  })
})
