import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  composeGatheringLocation,
  gatheringLocationSummary,
} from './gatheringLocation.ts'

const ARRABRI = 'Arrabri Community House'
const ARRABRI_ADDRESS = '42 Allambanan Drive, Bayswater North VIC 3153'

describe('Example A — a public venue', () => {
  // Venue name: Arrabri Community House
  // Public address: 42 Allambanan Drive, Bayswater North VIC 3153
  // Private address: blank
  const input = {
    attendanceFormat: 'in_person' as const,
    venueName: ARRABRI,
    publicAddress: ARRABRI_ADDRESS,
    privateAddress: null,
  }

  it('shows the name and the address once each', () => {
    const out = composeGatheringLocation(input)
    assert.equal(out.name, ARRABRI)
    assert.equal(out.address, ARRABRI_ADDRESS)
    assert.equal(out.isPrivateAddress, false)
    assert.equal(out.hasLocation, true)
  })

  it('shows a confirmed attendee exactly the same thing', () => {
    // The private address is blank, so there is nothing more to give
    // them — and they must not be shown nothing.
    const attendee = composeGatheringLocation({ ...input, privateAddress: null })
    assert.deepEqual(attendee, composeGatheringLocation(input))
    assert.equal(attendee.address, ARRABRI_ADDRESS)
  })
})

describe('Example B — a private venue', () => {
  const base = {
    attendanceFormat: 'in_person' as const,
    venueName: 'Private residence',
    publicAddress: 'South Croydon, Victoria',
  }

  it('a public viewer sees the suburb', () => {
    // The server sends no private address to this viewer at all.
    const out = composeGatheringLocation({ ...base, privateAddress: null })
    assert.equal(out.name, 'Private residence')
    assert.equal(out.address, 'South Croydon, Victoria')
    assert.equal(out.isPrivateAddress, false)
  })

  it('a confirmed attendee sees the street address instead', () => {
    const out = composeGatheringLocation({
      ...base, privateAddress: '62 Longview Road, South Croydon',
    })
    assert.equal(out.name, 'Private residence')
    assert.equal(out.address, '62 Longview Road, South Croydon')
    assert.equal(out.isPrivateAddress, true)
  })

  it('the attendee is not shown both addresses', () => {
    const out = composeGatheringLocation({
      ...base, privateAddress: '62 Longview Road, South Croydon',
    })
    assert.ok(!out.address!.includes('South Croydon, Victoria'))
  })
})

describe('the private address fallback', () => {
  const base = {
    attendanceFormat: 'in_person' as const,
    venueName: 'The Studio',
    publicAddress: '14 King Street, Richmond',
  }

  it('a blank private address falls back to the public one', () => {
    for (const blank of [null, undefined, '', '   ']) {
      const out = composeGatheringLocation({ ...base, privateAddress: blank })
      assert.equal(out.address, '14 King Street, Richmond', String(blank))
      assert.equal(out.isPrivateAddress, false)
    }
  })

  it('a populated private address wins', () => {
    const out = composeGatheringLocation({
      ...base, privateAddress: 'Studio 4, rear entrance, 14 King Street',
    })
    assert.equal(out.address, 'Studio 4, rear entrance, 14 King Street')
    assert.equal(out.isPrivateAddress, true)
  })

  it('an identical private address is not announced as private', () => {
    // The creator typed the same thing twice, or an older record
    // carries it in both columns. Shown once, unmarked — there is no
    // extra detail to flag.
    const out = composeGatheringLocation({
      ...base, privateAddress: '14 King Street, Richmond',
    })
    assert.equal(out.address, '14 King Street, Richmond')
    assert.equal(out.isPrivateAddress, false)
  })

  it('differences in case and punctuation still count as identical', () => {
    const out = composeGatheringLocation({
      ...base, privateAddress: '14 King Street Richmond',
    })
    assert.equal(out.isPrivateAddress, false)
  })

  it('a longer private address that merely starts the same is private', () => {
    const out = composeGatheringLocation({
      ...base, privateAddress: '14 King Street, Richmond — upstairs, ring bell',
    })
    assert.equal(out.isPrivateAddress, true)
    assert.ok(out.address!.includes('ring bell'))
  })
})

describe('removing a repeated venue name', () => {
  it('strips a leading repeat after a dash', () => {
    // The reported Gathering: the creator put the venue into the
    // public address as well as the name.
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: ARRABRI,
      publicAddress: `${ARRABRI} - 42 Allambanan Drive, Bayswater North`,
      privateAddress: null,
    })
    assert.equal(out.name, ARRABRI)
    assert.equal(out.address, '42 Allambanan Drive, Bayswater North')
  })

  it('strips it after a comma or a middot', () => {
    for (const sep of [',', ' ·', ' –', ' —', ' |']) {
      const out = composeGatheringLocation({
        attendanceFormat: 'in_person',
        venueName: 'The Studio',
        publicAddress: `The Studio${sep} 14 King Street`,
      })
      assert.equal(out.address, '14 King Street', sep)
    }
  })

  it('drops the address entirely when it only repeats the name', () => {
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: ARRABRI,
      publicAddress: ARRABRI,
    })
    assert.equal(out.name, ARRABRI)
    assert.equal(out.address, null)
    assert.equal(out.hasLocation, true)
  })

  it('does not strip on whitespace alone', () => {
    // "The Studio Annexe" is a different place, not a repeat.
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: 'The Studio',
      publicAddress: 'The Studio Annexe, 14 King Street',
    })
    assert.equal(out.address, 'The Studio Annexe, 14 King Street')
  })

  it('keeps an address that merely overlaps in the middle', () => {
    // "Do not remove meaningful address details merely because two
    // strings partially overlap."
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: 'King Street',
      publicAddress: '14 King Street, Richmond',
    })
    assert.equal(out.address, '14 King Street, Richmond')
  })

  it('never leaves an empty address behind', () => {
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: 'The Studio',
      publicAddress: 'The Studio —   ',
    })
    assert.ok(out.address === null || out.address.length > 0)
  })

  it('strips the name from a private address too', () => {
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: ARRABRI,
      publicAddress: 'Bayswater North',
      privateAddress: `${ARRABRI}, 42 Allambanan Drive`,
    })
    assert.equal(out.address, '42 Allambanan Drive')
    assert.equal(out.isPrivateAddress, true)
  })
})

describe('partial and empty records', () => {
  it('a public address with no venue name', () => {
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      publicAddress: 'South Croydon, Victoria',
    })
    assert.equal(out.name, null)
    assert.equal(out.address, 'South Croydon, Victoria')
    assert.equal(out.hasLocation, true)
  })

  it('a venue name with no address — the pre-migration-114 shape', () => {
    // EMBODY's Term 4 Gatherings: "Private residence, South Croydon,
    // Vic" in the name, nothing in the locality. They must keep
    // saying exactly that.
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: 'Private residence, South Croydon, Vic',
    })
    assert.equal(out.name, 'Private residence, South Croydon, Vic')
    assert.equal(out.address, null)
    assert.equal(out.hasLocation, true)
  })

  it('nothing filled in', () => {
    const out = composeGatheringLocation({ attendanceFormat: 'in_person' })
    assert.equal(out.hasLocation, false)
    assert.equal(out.name, null)
    assert.equal(out.address, null)
  })

  it('an online Gathering has no location at all', () => {
    // Even if the columns still hold a venue from when it was in
    // person — which they do, because nothing clears them.
    const out = composeGatheringLocation({
      attendanceFormat: 'online',
      venueName: ARRABRI,
      publicAddress: ARRABRI_ADDRESS,
      privateAddress: '62 Longview Road',
    })
    assert.equal(out.hasLocation, false)
    assert.equal(out.name, null)
    assert.equal(out.address, null)
  })

  it('hybrid behaves like in person', () => {
    const out = composeGatheringLocation({
      attendanceFormat: 'hybrid',
      venueName: ARRABRI,
      publicAddress: ARRABRI_ADDRESS,
    })
    assert.equal(out.name, ARRABRI)
    assert.equal(out.address, ARRABRI_ADDRESS)
  })

  it('an unknown or absent format is treated as physical', () => {
    // Older rows and defensive callers. Showing the public location is
    // safe; the private half never arrives for an unentitled viewer.
    for (const fmt of [null, undefined, '']) {
      const out = composeGatheringLocation({
        attendanceFormat: fmt, publicAddress: 'South Croydon, Victoria',
      })
      assert.equal(out.address, 'South Croydon, Victoria', String(fmt))
    }
  })
})

describe('it cannot disclose what it was not given', () => {
  it('a withheld private address cannot appear', () => {
    // The server sends null to an unentitled viewer. There is no path
    // by which this function invents one.
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: 'Private residence',
      publicAddress: 'South Croydon, Victoria',
      privateAddress: null,
    })
    assert.ok(!JSON.stringify(out).includes('Longview'))
    assert.equal(out.isPrivateAddress, false)
  })

  it('arrival instructions are never folded into the address', () => {
    // They are a separate field with the same gate, rendered on their
    // own. This module has no parameter for them, which is the point.
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: 'Private residence',
      publicAddress: 'South Croydon, Victoria',
      privateAddress: '62 Longview Road, South Croydon',
    })
    assert.ok(!out.address!.includes('driveway'))
  })
})

describe('the one-line summary', () => {
  it('joins the format with what there is', () => {
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: ARRABRI,
      publicAddress: `${ARRABRI} - 42 Allambanan Drive`,
    })
    assert.equal(
      gatheringLocationSummary('In person', out),
      'In person · Arrabri Community House, 42 Allambanan Drive',
    )
  })

  it('is just the format when there is no location', () => {
    const out = composeGatheringLocation({ attendanceFormat: 'online' })
    assert.equal(gatheringLocationSummary('Online', out), 'Online')
  })

  it('does not repeat the venue name', () => {
    const out = composeGatheringLocation({
      attendanceFormat: 'in_person',
      venueName: ARRABRI,
      publicAddress: ARRABRI,
    })
    assert.equal(
      gatheringLocationSummary('In person', out),
      `In person · ${ARRABRI}`,
    )
  })
})

describe('the Gathering page uses this and nothing else', () => {
  const PAGE = join(
    process.cwd(), 'src', 'app', 'spaces', '[slug]', 'events', '[eventId]',
    'page.tsx',
  )
  const page = () => readFileSync(PAGE, 'utf8')

  it('composes the location through this module', () => {
    const source = page()
    assert.ok(
      /composeGatheringLocation\(\{/.test(source),
      'the Gathering page no longer composes its location here',
    )
    assert.ok(
      /privateAddress: event\.venue_address/.test(source),
      'the private address is no longer passed to the composer',
    )
  })

  it('no longer prints three consecutive location lines', () => {
    // The defect: `whereSummary` (the public address), then
    // `venue_name`, then `venue_address` — rendered one after another,
    // with the first two frequently identical.
    const source = page()
    assert.ok(
      !/whereSummary/.test(source),
      'the old combined where-line is back alongside the composer',
    )
    assert.ok(
      !/event\.venue_address !== event\.venue_locality/.test(source),
      'the page is comparing address strings itself again',
    )
  })

  it('renders the name and the address at most once each', () => {
    const source = page()
    const panel = source.slice(
      source.indexOf('{location.hasLocation ? ('),
      source.indexOf("{event.attendance_format !== 'in_person' && event.location_url"),
    )
    assert.equal((panel.match(/\{location\.name\}/g) ?? []).length, 1)
    assert.equal((panel.match(/\{location\.address\}/g) ?? []).length, 1)
    // And it must not reach around the composer for the raw fields.
    for (const raw of ['event.venue_name', 'event.venue_locality', 'event.venue_address']) {
      assert.ok(!panel.includes(raw), `the panel still reads ${raw} directly`)
    }
  })

  it('does not label the address for the viewer', () => {
    // There was an italic "Shared with confirmed attendees" under a
    // private address. Removed deliberately: a member reading their
    // own Gathering does not need telling which column the line came
    // from, and it raised a question rather than answering one.
    //
    // `isPrivateAddress` is still computed and still tested above —
    // the composer knows the difference, no surface currently says it.
    const source = page()
    assert.ok(
      !/Shared with confirmed attendees/.test(source),
      'the attendee-only label is back on the Gathering page',
    )
  })

  it('arrival instructions stay in their own block', () => {
    // Same gate, separate rendering — they are not an address.
    const source = page()
    assert.ok(/event\.access_instructions && \(/.test(source))
    const panel = source.slice(
      source.indexOf('{location.hasLocation ? ('),
      source.indexOf("{event.attendance_format !== 'in_person' && event.location_url"),
    )
    assert.ok(!panel.includes('access_instructions'))
  })
})
