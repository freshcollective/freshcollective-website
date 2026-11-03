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
    // The label is "Public address" since the location fields were
    // reworded; the state it writes is still venueLocality, because
    // the column is still venue_locality.
    const source = form()
    const field = source.slice(source.indexOf('Public address'))
    assert.ok(
      /value=\{venueLocality\}/.test(field),
      'the Public address input is not bound to venueLocality',
    )
    assert.ok(
      /onChange=\{\(e\) => setVenueLocality\(e\.target\.value\)\}/.test(field),
      'typing in Public address no longer updates venueLocality',
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

describe('the editor marks public and private fields plainly', () => {
  it('the private address sits under an attendees-only heading', () => {
    // The privacy split must survive any edit to this section. The
    // heading was "Venue and attendee details", which bundled a public
    // field (venue name) in with a private one; it now names only the
    // private half, and the venue name has moved out of the box.
    const source = form()
    const box = source.slice(source.indexOf('Only for confirmed attendees'))
    assert.ok(
      /Shared with people who have a confirmed place/.test(box),
      'the attendee-only wording around the private address is gone',
    )
    assert.ok(
      /Never shown on the public\s+Gathering page or in announcement emails/
        .test(box),
      'the box no longer says where the private address is not shown',
    )
    const privateField = source.slice(
      source.indexOf('Private address (if different)'),
    )
    assert.ok(
      /value=\{venueAddress\}/.test(privateField),
      'Private address is not bound to venueAddress',
    )
  })

  it('the venue name is outside the attendees-only box', () => {
    // It is public, and describing it as attendee detail was the
    // confusion this reorder fixes.
    const source = form()
    assert.ok(
      source.indexOf('Venue name')
        < source.indexOf('Only for confirmed attendees'),
      'Venue name has moved back inside the attendees-only box',
    )
    const field = source.slice(source.indexOf('Venue name'))
    assert.ok(
      /The name of the place where people will gather\. Shown\s+publicly\./
        .test(field),
      'Venue name no longer states that it is public',
    )
  })

  it('the Public address help text permits a full address', () => {
    // Deliberately changed. The old wording said "never a street
    // address", which contradicted the agreed model — a creator
    // decides what they are comfortable publishing.
    const source = form()
    assert.ok(
      /comfortable sharing publicly\. This can be a\s+suburb or a full address\./
        .test(source),
      'the Public address guidance is gone',
    )
    assert.ok(
      !/never a\s+street address/.test(source),
      'the editor forbids a street address in the public field again',
    )
  })

  it('an attendee is told when the public address is enough', () => {
    // The fallback, stated where the creator decides: leaving Private
    // address blank shows attendees the public one.
    assert.ok(
      /Leave blank if the public address is all they\s+need/.test(form()),
      'the private-address fallback is no longer explained',
    )
  })
})
