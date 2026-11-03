import { strict as assert } from 'node:assert'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  isStandaloneGathering,
  seriesLifecycleLabel,
  seriesLifecycleStyle,
  seriesOccurrenceCount,
  standaloneGatherings,
} from './seriesArchive.ts'

const SRC = join(process.cwd(), 'src')
const UPCOMING = join(SRC, 'app', 'creator-studio', 'gatherings', 'page.tsx')
const ARCHIVE = join(
  SRC, 'app', 'creator-studio', 'gatherings', 'archive', 'page.tsx',
)
const BAND = join(
  SRC, 'app', 'creator-studio', 'gatherings', 'GatheringSeriesBand.tsx',
)
const CARD = join(SRC, 'components', 'creator', 'SeriesCard.tsx')

describe('which Gatherings are standalone', () => {
  it('a Gathering with no series is standalone', () => {
    assert.equal(isStandaloneGathering({}), true)
    assert.equal(
      isStandaloneGathering({ series_id: null, recurrence_series_id: null }),
      true,
    )
  })

  it('an occurrence of a Series is not', () => {
    // It is reachable through the Series card, so listing it again is
    // what made a thirty-session term read as thirty Gatherings.
    assert.equal(isStandaloneGathering({ series_id: 'es_1' }), false)
  })

  it('a bulk-created occurrence with no Series IS still listed', () => {
    // The important one. A bulk create with no Series chosen stamps
    // `recurrence_series_id` and creates no EventSeries row, so there
    // is no Series page to reach it through — hiding it would make it
    // unreachable rather than de-duplicated.
    assert.equal(
      isStandaloneGathering({ recurrence_series_id: 'rs_1', series_id: null }),
      true,
    )
  })

  it('a bulk-created occurrence that also belongs to a Series is not', () => {
    assert.equal(
      isStandaloneGathering({ recurrence_series_id: 'rs_1', series_id: 'es_1' }),
      false,
    )
  })

  it('splits a mixed list', () => {
    const events = [
      { id: 'a' }, { id: 'b', series_id: 'es_1' },
      { id: 'c', recurrence_series_id: 'rs_1' },
      { id: 'd', series_id: 'es_1' },
    ]
    assert.deepEqual(
      standaloneGatherings(events).map((e) => e.id), ['a', 'c'],
    )
    assert.equal(seriesOccurrenceCount(events), 2)
  })

  it('handles an empty list', () => {
    assert.deepEqual(standaloneGatherings([]), [])
    assert.equal(seriesOccurrenceCount([]), 0)
  })
})

describe('lifecycle presentation', () => {
  it('labels each state', () => {
    assert.equal(seriesLifecycleLabel('completed'), 'Completed')
    assert.equal(seriesLifecycleLabel('archived'), 'Archived')
    assert.equal(seriesLifecycleLabel('running'), 'Running')
    assert.equal(seriesLifecycleLabel('scheduled'), 'Scheduled')
    assert.equal(seriesLifecycleLabel('draft'), 'Draft')
  })

  it('falls back to the stored status for an older payload', () => {
    // The field is derived at read time and callers that pass no scope
    // may not have it.
    assert.equal(seriesLifecycleLabel('published'), 'Published')
  })

  it('never renders a blank pill', () => {
    assert.equal(seriesLifecycleLabel(null), 'Series')
    assert.equal(seriesLifecycleLabel(undefined), 'Series')
    assert.equal(seriesLifecycleLabel('something_new'), 'something_new')
  })

  it('puts finished and put-away states in the same quiet grey', () => {
    const completed = seriesLifecycleStyle('completed')
    const archived = seriesLifecycleStyle('archived')
    assert.deepEqual(completed, archived)
    assert.ok(/12,24,38/.test(completed.color))
  })

  it('keeps current states in the teal the band established', () => {
    assert.ok(/0f766e/.test(seriesLifecycleStyle('running').color))
    assert.ok(/0f766e/.test(seriesLifecycleStyle('published').color))
  })

  it('gives a draft the gold treatment it already had', () => {
    assert.ok(/8a6a1f/.test(seriesLifecycleStyle('draft').color))
    assert.ok(/8a6a1f/.test(seriesLifecycleStyle(null).color))
  })
})

/**
 * The pages are Server Components and this harness has no DOM, so
 * their wiring is asserted against the source. Shape checks: they fail
 * loudly if a view stops fetching Series or starts listing occurrences
 * again, which is what a regression here looks like.
 */
describe('Archives shows Series', () => {
  const archive = () => readFileSync(ARCHIVE, 'utf8')

  it('fetches them, scoped to the archive', () => {
    // The root cause: this page only ever fetched events.
    const source = archive()
    assert.ok(
      /getCreatorGatheringSeriesList\(primarySpace\.slug, 'archive'\)/.test(source),
      'the archive page does not fetch archived Series',
    )
  })

  it('renders them with the shared card', () => {
    const source = archive()
    assert.ok(/<SeriesCard series=\{s\} \/>/.test(source))
    assert.ok(existsSync(CARD), CARD)
  })

  it('groups them above the standalone Gatherings, as Upcoming does', () => {
    const source = archive()
    const seriesHeading = source.indexOf('Gathering Series')
    const standaloneHeading = source.indexOf('Standalone Gatherings')
    assert.ok(seriesHeading > -1, 'no Series section')
    assert.ok(standaloneHeading > -1, 'no Standalone section')
    assert.ok(seriesHeading < standaloneHeading, 'Series is below standalone')
  })

  it('does not list Series occurrences as standalone Gatherings', () => {
    const source = archive()
    assert.ok(/const events = standaloneGatherings\(allEvents\)/.test(source))
    assert.ok(
      !/\{allEvents\.map/.test(source),
      'the unfiltered list is being rendered again',
    )
  })

  it('says how many sessions are inside the Series instead', () => {
    // So a creator can tell the difference between "filtered" and
    // "missing".
    assert.ok(/seriesOccurrenceCount\(allEvents\)/.test(archive()))
    assert.ok(/inside the Series above/.test(archive()))
  })

  it('is empty only when both groups are empty', () => {
    const source = archive()
    assert.ok(
      /const isEmpty = events\.length === 0 && series\.length === 0/.test(source),
      'the empty state ignores Series',
    )
    assert.ok(/\) : isEmpty \? \(/.test(source))
  })

  it('keeps the Manage link on every archived Gathering', () => {
    assert.ok(/<CreatorEventRow/.test(archive()))
    assert.ok(/allowDuplicate/.test(archive()))
  })
})

describe('Upcoming keeps current Series', () => {
  it('fetches them, scoped to upcoming', () => {
    assert.ok(
      /getCreatorGatheringSeriesList\(primarySpace\.slug, 'upcoming'\)/
        .test(readFileSync(UPCOMING, 'utf8')),
      'the Gatherings page is not scoping its Series fetch',
    )
  })

  it('shares the occurrence filter with Archives', () => {
    // Two lists of the same thing must not disagree about what counts
    // as standalone.
    const source = readFileSync(UPCOMING, 'utf8')
    assert.ok(/standaloneGatherings\(upcoming\)/.test(source))
    assert.ok(
      !/upcoming\.filter\(\(e\) => !e\.series_id\)/.test(source),
      'the filter is inline again',
    )
  })

  it('still renders the Series band', () => {
    assert.ok(/<GatheringSeriesBand/.test(readFileSync(UPCOMING, 'utf8')))
  })
})

describe('one Series card, both views', () => {
  it('the band renders through it rather than its own markup', () => {
    const band = readFileSync(BAND, 'utf8')
    assert.ok(/<SeriesCard series=\{s\} \/>/.test(band))
    assert.ok(
      !/statusStyle\(/.test(band),
      'the band has its own status pill again',
    )
  })

  it('the card shows what an archived Series needs', () => {
    const card = readFileSync(CARD, 'utf8')
    for (const field of [
      'series.title', 'series.cover_image_url', 'series.gathering_count',
      'seriesDateSummary', 'seriesLifecycleLabel',
    ]) {
      assert.ok(card.includes(field), `the card lost ${field}`)
    }
  })

  it('links to the existing Series editor', () => {
    // Not a separate archived-Series management view.
    assert.ok(
      /href=\{`\/creator-studio\/gathering-series\/\$\{series\.slug\}`\}/
        .test(readFileSync(CARD, 'utf8')),
    )
  })

  it('says Ongoing rather than showing a blank end date', () => {
    const card = readFileSync(CARD, 'utf8')
    assert.ok(/if \(!endsAt\) return `Starts \$\{start\} · Ongoing`/.test(card))
  })

  it('uses the calendar date formatter, not the instant one', () => {
    // A Series' dates are calendar days stored as …T23:59:59;
    // converting that through a timezone rolls the end date forward.
    const card = readFileSync(CARD, 'utf8')
    assert.ok(/formatCalendarDate/.test(card))
    assert.ok(!/parseServerDatetime/.test(card))
  })

  it('is responsive — two columns on tablet, one on a phone', () => {
    for (const path of [ARCHIVE, BAND]) {
      assert.ok(
        /grid gap-4 sm:grid-cols-2/.test(readFileSync(path, 'utf8')),
        `${path} is not a responsive Series grid`,
      )
    }
  })
})
