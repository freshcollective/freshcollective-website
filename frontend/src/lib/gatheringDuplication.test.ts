import { strict as assert } from 'node:assert'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  DUPLICATE_SUCCESS_MESSAGE,
  canDuplicateGathering,
  duplicateDraftHref,
  duplicateEndpoint,
  duplicateErrorMessage,
  duplicateIneligibleReason,
} from './gatheringDuplication.ts'

const SRC = join(process.cwd(), 'src')
const CARD = join(SRC, 'app', 'creator-studio', 'gatherings', 'StandaloneGatheringCard.tsx')
const ROW = join(SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'CreatorEventRow.tsx')
const BUTTON = join(SRC, 'components', 'creator', 'DuplicateGatheringButton.tsx')
const ARCHIVE = join(SRC, 'app', 'creator-studio', 'gatherings', 'archive', 'page.tsx')

describe('eligibility', () => {
  it('a standalone Gathering may be duplicated', () => {
    assert.equal(canDuplicateGathering({ id: 'e_1' }), true)
    assert.equal(
      canDuplicateGathering({ id: 'e_1', series_id: null, recurrence_series_id: null }),
      true,
    )
  })

  it('every lifecycle state is eligible', () => {
    // Draft, published, completed and archived all copy the same
    // configuration. Nothing about eligibility reads a status.
    for (const extra of [{}, { status: 'active' }, { status: 'archived' }, { status: 'cancelled' }]) {
      assert.equal(canDuplicateGathering({ id: 'e_1', ...extra }), true)
    }
  })

  it('a Series occurrence may not', () => {
    assert.equal(canDuplicateGathering({ id: 'e_1', series_id: 'es_1' }), false)
  })

  it('a bulk recurrence occurrence may not', () => {
    // Matters on its own: the Gatherings list filters its Standalone
    // section on `series_id` only, so one of these appears there — and
    // the endpoint would refuse it.
    assert.equal(
      canDuplicateGathering({ id: 'e_1', recurrence_series_id: 'rs_1' }),
      false,
    )
  })

  it('explains itself when it refuses', () => {
    assert.equal(duplicateIneligibleReason({ id: 'e_1' }), null)
    const why = duplicateIneligibleReason({ id: 'e_1', series_id: 'es_1' })
    assert.ok(why && /belongs to a series/i.test(why), why)
  })
})

describe('where the request goes and where the creator lands', () => {
  it('posts to the existing endpoint', () => {
    // The backend action has existed since migration 175. This is a
    // button for it, not a second duplication system.
    assert.equal(
      duplicateEndpoint('moonlit-circle', 'e_1'),
      '/api/creator/spaces/moonlit-circle/events/e_1/duplicate',
    )
  })

  it('opens the new draft, not the original', () => {
    assert.equal(
      duplicateDraftHref('moonlit-circle', 'e_new'),
      '/creator/spaces/moonlit-circle/events/e_new',
    )
    assert.ok(!duplicateDraftHref('moonlit-circle', 'e_new').includes('e_1'))
  })
})

describe('feedback', () => {
  it('says a draft was created, not that anything changed', () => {
    assert.ok(/draft created/i.test(DUPLICATE_SUCCESS_MESSAGE))
    assert.ok(/date and time/i.test(DUPLICATE_SUCCESS_MESSAGE))
    // Nothing that could read as "the original was modified".
    assert.ok(!/updated|changed|published/i.test(DUPLICATE_SUCCESS_MESSAGE))
  })

  it('shows our own 400 text verbatim', () => {
    // The Series refusal is written server-side and is the one message
    // a creator most needs to read.
    const detail = 'This Gathering belongs to a series, so it cannot be '
      + 'duplicated on its own. Add a session to the series instead.'
    assert.equal(duplicateErrorMessage(400, detail), detail)
    assert.equal(duplicateErrorMessage(409, 'A conflict.'), 'A conflict.')
  })

  it('never leaks a bare framework message', () => {
    for (const [status, detail] of [
      [404, 'Not Found'], [500, 'Internal Server Error'], [502, null], [0, null],
    ] as [number, unknown][]) {
      const message = duplicateErrorMessage(status, detail)
      assert.ok(!/Internal Server Error/.test(message), message)
      assert.ok(!/^Not Found$/.test(message), message)
    }
  })

  it('names permission and missing-record failures plainly', () => {
    assert.ok(/permission/i.test(duplicateErrorMessage(403, null)))
    assert.ok(/could not be found/i.test(duplicateErrorMessage(404, 'Not Found')))
  })
})

describe('the button', () => {
  const button = () => readFileSync(BUTTON, 'utf8')

  it('exists where the cards import it from', () => {
    assert.ok(existsSync(BUTTON), BUTTON)
  })

  it('calls the endpoint helper rather than building a URL', () => {
    const source = button()
    assert.ok(/duplicateEndpoint\(spaceSlug, event\.id\)/.test(source))
    assert.ok(/method: 'POST'/.test(source))
    assert.ok(/credentials: 'include'/.test(source))
  })

  it('navigates to the created draft, by the id the server returned', () => {
    const source = button()
    assert.ok(
      /duplicateDraftHref\(spaceSlug, created\.id\)/.test(source),
      'the button no longer opens the draft the server created',
    )
  })

  it('refreshes the list it leaves behind', () => {
    assert.ok(/router\.refresh\(\)/.test(button()))
  })

  it('refuses an ineligible Gathering itself', () => {
    // The card checks too. This is the case where a list filter
    // changes and nobody remembers.
    assert.ok(/if \(!canDuplicateGathering\(event\)\) return null/.test(button()))
  })

  it('cannot be double-submitted', () => {
    const source = button()
    assert.ok(/if \(busy\) return/.test(source))
    assert.ok(/disabled=\{busy\}/.test(source))
  })

  it('is a button, not a link', () => {
    // It posts. A link that mutates is wrong, and these cards are
    // Server Components whose chrome is already an <a>.
    const source = button()
    assert.ok(/type="button"/.test(source))
    assert.ok(!/<Link/.test(source))
  })
})

describe('where it appears', () => {
  it('on the Gatherings card, outside the card link', () => {
    const source = readFileSync(CARD, 'utf8')
    assert.ok(/<DuplicateGatheringButton spaceSlug=\{slug\} event=\{event\} \/>/.test(source))
    // An interactive control inside an <a> is invalid and unreachable
    // by keyboard — the same reason the Attendance link is a sibling.
    const linkStart = source.indexOf('<Link href={editHref}')
    const linkEnd = source.indexOf('</Link>', linkStart)
    const buttonAt = source.indexOf('<DuplicateGatheringButton')
    assert.ok(buttonAt > linkEnd, 'Duplicate is nested inside the card link')
  })

  it('on archive rows, opted in', () => {
    const archive = readFileSync(ARCHIVE, 'utf8')
    assert.ok(/allowDuplicate/.test(archive), 'the archive no longer offers Duplicate')
  })

  it('not on Series editor rows', () => {
    // The same row component lists a Series' occurrences, none of
    // which can be duplicated. Off unless asked for.
    const row = readFileSync(ROW, 'utf8')
    assert.ok(
      /allowDuplicate = false/.test(row),
      'Duplicate is now on by default for every CreatorEventRow',
    )
    assert.ok(
      /allowDuplicate && canDuplicateGathering\(event\)/.test(row),
      'the row no longer checks eligibility as well as the opt-in',
    )
  })
})

describe('a dateless draft renders without a broken date', () => {
  it('the card and the row both have a label for it', () => {
    for (const path of [CARD, ROW]) {
      const source = readFileSync(path, 'utf8')
      assert.ok(
        /if \(!iso\) return NO_DATE_LABEL/.test(source),
        `${path} renders a null start date through the formatter`,
      )
    }
  })

  it('the editor opens with an empty date field', () => {
    // Which is the prompt: the creator must choose a time, and
    // publishing without one is refused server-side.
    const form = readFileSync(
      join(SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'EventForm.tsx'),
      'utf8',
    )
    assert.ok(
      /event\?\.starts_at \? toLocalDatetime\(event\.starts_at\) : ''/.test(form),
      'the editor no longer handles a dateless draft',
    )
  })

  it('the shared label is one string', () => {
    const dateTime = readFileSync(join(SRC, 'lib', 'dateTime.ts'), 'utf8')
    assert.ok(/export const NO_DATE_LABEL = /.test(dateTime))
  })
})
