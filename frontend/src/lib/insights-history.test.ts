import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  CARD,
  CARD_SURFACES,
  EMPHASIS,
  HUE_MARK,
  HUE_UI,
  INK,
  STATUS,
  SURFACE_ORDER,
  surfaceForGroup,
} from './insights-palette.ts'

import {
  QUALITY_LABEL,
  axisLabelSpace,
  directLabelSpace,
  estimateTextWidth,
  MIN_COMPARABLE_PERIODS,
  byGrowth,
  bySize,
  collectiveStandings,
  historyQuality,
  isQuietening,
  pointQuality,
  populationNotes,
  seriesKey,
  tooltipLeft,
  xLabelCapacity,
  type CohortOffset,
  type CohortRow,
  type Creator,
  cohortLabel,
  formatRetention,
  reachedOffsets,
  retentionRate,
  CREATOR_STAGES,
  byOperator,
  stageCounts,
  type HistoryPoint,
  type HistorySeries,
  CHART_HUES,
  HUE_STROKE,
  compactCount,
  compactMoney,
  dashRuns,
  describeSeries,
  emptyBucketIndices,
  formatAxisValue,
  formatExactValue,
  hasGaps,
  linePath,
  niceDomain,
  niceStep,
  pointCaveats,
  scaleY,
  shortBucketLabel,
  stackAt,
  stackTotals,
  valueSegments,
  spreadLabels,
  xTickIndices,
} from './insights-history.ts'
import { formatMoney } from './insights.ts'

/**
 * The chart layer's arithmetic.
 *
 * Every mistake a chart can make here is an arithmetic mistake with a
 * visual consequence, which is why this logic lives in a module rather
 * than inside a component: a gap drawn as a zero, a snapshot summed
 * into a total, a bar measured against a baseline that is not zero, a
 * part period drawn at full strength. None of those are caught by
 * looking at the page, because all of them produce a plausible picture.
 */

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const read = (p: string) => readFileSync(join(ROOT, p), 'utf8')
const withoutDocComments = (src: string) => src.replace(/\/\*\*[\s\S]*?\*\//g, '')
/** Collapse wrapped JSX prose so a sentence can be read as a sentence. */
const flatten = (src: string) => src.replace(/\s+/g, ' ')

function point(over: Partial<HistoryPoint> = {}): HistoryPoint {
  return {
    label: 'w/c 2026-10-05',
    starts_on: '2026-10-05',
    ends_on: '2026-10-11',
    value: 10,
    available: true,
    unavailable_reason: null,
    provenance: 'observed',
    complete: true,
    clipped: false,
    days_present: 7,
    days_expected: 7,
    partial_data: false,
    ...over,
  }
}

function series(over: Partial<HistorySeries> = {}): HistorySeries {
  return {
    key: 'unique_members',
    display_name: 'Unique members',
    unit: 'count',
    aggregation: 'snapshot',
    source: 'stored',
    definition: 'Distinct people holding a membership.',
    source_of_truth: 'space_memberships.joined_at / removed_at',
    date_basis: 'none',
    availability: 'full',
    limitations: null,
    observation_only: false,
    qualifiers: {},
    collective_id: null,
    collective_name: null,
    points: [point()],
    ...over,
  }
}

// ---------------------------------------------------------------------------

describe('the y axis is always anchored to zero', () => {
  test('a domain over positive values starts at zero', () => {
    const d = niceDomain([1180, 1190, 1200])
    assert.equal(d.min, 0)
    assert.ok(d.max >= 1200)
  })

  test('without a zero baseline a 2% change would look like a cliff', () => {
    // The anti-pattern this guards: truncating the axis to 1180–1200
    // makes a 1.7% rise fill the whole plot.
    const d = niceDomain([1180, 1200])
    const span = d.max - d.min
    const drawn = (1200 - 1180) / span
    assert.ok(drawn < 0.2, `a 1.7% change should not occupy ${drawn} of the plot`)
  })

  test('negative values are honoured rather than clamped', () => {
    // Contribution after processing costs can genuinely be negative,
    // and that is the month worth looking at.
    const d = niceDomain([-500, 200])
    assert.ok(d.min <= -500)
    assert.ok(d.max >= 200)
    assert.ok(d.ticks.includes(0), 'zero must be a tick when the range crosses it')
  })

  test('an all-null series yields a safe domain rather than NaN', () => {
    const d = niceDomain([null, null])
    assert.equal(d.min, 0)
    assert.ok(Number.isFinite(d.max) && d.max > 0)
  })

  test('an all-zero series does not collapse to a zero-height plot', () => {
    const d = niceDomain([0, 0, 0])
    assert.ok(d.max > d.min)
  })

  test('ticks are round numbers, never floating-point debris', () => {
    for (const values of [[3], [7], [23], [1234], [0.3]]) {
      for (const t of niceDomain(values).ticks) {
        assert.equal(t, Math.round(t * 1e6) / 1e6, `tick ${t} is not clean`)
      }
    }
  })

  test('the step is always a 1, 2 or 5 times a power of ten', () => {
    for (const rough of [0.3, 1, 1.5, 3, 7, 11, 260, 3400]) {
      const step = niceStep(rough)
      const mantissa = step / 10 ** Math.floor(Math.log10(step))
      assert.ok([1, 2, 5, 10].includes(Math.round(mantissa)), `step ${step}`)
    }
  })

  test('scaleY puts the domain minimum at the bottom', () => {
    const d = { min: 0, max: 100, ticks: [0, 100] }
    assert.equal(scaleY(0, d, 200), 200)
    assert.equal(scaleY(100, d, 200), 0)
    assert.equal(scaleY(50, d, 200), 100)
  })
})

describe('a missing period is a break in the line, never a zero', () => {
  test('a gap splits the line into separate runs', () => {
    assert.deepEqual(valueSegments([1, 2, null, 4, 5]), [[0, 1], [3, 4]])
  })

  test('nothing joins across the gap', () => {
    const runs = valueSegments([1, null, 3])
    // Two runs of one, so no path is drawn between February and April.
    assert.deepEqual(runs, [[0], [2]])
  })

  test('a fully known series is one run', () => {
    assert.deepEqual(valueSegments([1, 2, 3]), [[0, 1, 2]])
  })

  test('an all-null series has no runs at all', () => {
    assert.deepEqual(valueSegments([null, null]), [])
  })

  test('a path is only drawn through points that exist', () => {
    const d = linePath([{ x: 0, y: 10 }, { x: 5, y: 20 }])
    assert.equal(d, 'M0 10 L5 20')
    assert.equal(linePath([]), '')
  })

  test('periods where nothing at all is known are identified', () => {
    const s = [
      series({ points: [point(), point({ available: false, value: null })] }),
      series({ key: 'b', points: [point(), point({ available: false, value: null })] }),
    ]
    assert.deepEqual(emptyBucketIndices(s), [1])
  })

  test('a period known to one series is not a blank', () => {
    const s = [
      series({ points: [point({ available: false, value: null })] }),
      series({ key: 'b', points: [point({ value: 4 })] }),
    ]
    assert.deepEqual(emptyBucketIndices(s), [])
  })

  test('hasGaps reports whether the panel needs to say so', () => {
    assert.equal(hasGaps([series()]), false)
    assert.equal(
      hasGaps([series({ points: [point({ available: false })] })]),
      true,
    )
  })
})

describe('an unfinished period is drawn as unfinished', () => {
  test('a join touching a partial period is dashed', () => {
    const runs = dashRuns([0, 1, 2], (i) => i === 2)
    assert.deepEqual(runs, [
      { dashed: false, indices: [0, 1] },
      { dashed: true, indices: [1, 2] },
    ])
  })

  test('consecutive joins of the same kind become one path', () => {
    const runs = dashRuns([0, 1, 2, 3], () => false)
    assert.equal(runs.length, 1)
    assert.deepEqual(runs[0].indices, [0, 1, 2, 3])
  })

  test('a lone point reports its own state', () => {
    assert.deepEqual(dashRuns([4], () => true), [{ dashed: true, indices: [4] }])
  })

  test('an empty run draws nothing', () => {
    assert.deepEqual(dashRuns([], () => true), [])
  })

  test('a part period is listed among a point caveats', () => {
    const notes = pointCaveats(point({ complete: false }))
    assert.ok(notes.some((n) => /not a full period/i.test(n)))
  })

  test('a clipped period says how few days it covers', () => {
    const notes = pointCaveats(point({ clipped: true, days_expected: 3 }))
    assert.ok(notes.some((n) => n.includes('3 days')))
  })

  test('a partly built period says how many days are behind it', () => {
    const notes = pointCaveats(
      point({ partial_data: true, days_present: 2, days_expected: 7 }),
    )
    assert.ok(notes.some((n) => n.includes('2 of 7 days')))
  })

  test('a sound period carries no caveats', () => {
    assert.deepEqual(pointCaveats(point()), [])
  })
})

describe('stacking only adds what is actually there', () => {
  test('segments sit on top of one another', () => {
    assert.deepEqual(stackAt([[2], [3]], 0), [
      { seriesIndex: 0, from: 0, to: 2 },
      { seriesIndex: 1, from: 2, to: 5 },
    ])
  })

  test('a missing series is skipped rather than treated as zero', () => {
    const segments = stackAt([[2], [null], [3]], 0)
    assert.deepEqual(segments.map((s) => s.seriesIndex), [0, 2])
    assert.equal(segments[1].to, 5, 'the stack closes up rather than leaving a hole')
  })

  test('a bucket with nothing known has no total', () => {
    assert.deepEqual(stackTotals([[null], [null]]), [null])
  })

  test('totals follow the top of the stack', () => {
    assert.deepEqual(stackTotals([[1, 2], [3, 4]]), [4, 6])
  })
})

describe('axis labels cannot collide', () => {
  test('few buckets are all labelled', () => {
    assert.deepEqual(xTickIndices(4, 8), [0, 1, 2, 3])
  })

  test('many buckets are thinned', () => {
    const ticks = xTickIndices(365, 8)
    assert.ok(ticks.length <= 10, `${ticks.length} labels would collide`)
  })

  test('the first and last period are always labelled', () => {
    for (const n of [5, 13, 52, 365]) {
      const ticks = xTickIndices(n, 6)
      assert.equal(ticks[0], 0)
      assert.equal(ticks[ticks.length - 1], n - 1)
    }
  })

  test('no bucket is labelled twice', () => {
    for (const n of [7, 30, 92, 365]) {
      const ticks = xTickIndices(n, 6)
      assert.equal(new Set(ticks).size, ticks.length)
    }
  })

  test('an empty chart has no ticks', () => {
    assert.deepEqual(xTickIndices(0, 6), [])
  })

  test('a weekly label reads as a date, not an ISO string', () => {
    assert.equal(shortBucketLabel('w/c 2026-10-05', 'weekly'), '5 Oct')
  })

  test('a monthly label drops the year it repeats', () => {
    assert.equal(shortBucketLabel('Oct 2026', 'monthly'), 'Oct')
  })

  test('a daily label reads as a date', () => {
    assert.equal(shortBucketLabel('2026-10-05', 'daily'), '5 Oct')
  })
})

describe('a number is formatted as the kind of number it is', () => {
  test('money is money at every magnitude', () => {
    assert.equal(compactMoney(50_00), '$50')
    assert.equal(compactMoney(1_234_00), '$1.2k')
    assert.equal(compactMoney(2_500_000_00), '$2.5m')
  })

  test('a negative amount keeps its sign', () => {
    assert.equal(compactMoney(-1_234_00), '-$1.2k')
    assert.equal(compactCount(-1500), '-1.5k')
  })

  test('counts are never formatted as currency', () => {
    assert.equal(formatAxisValue('count', 1500), '1.5k')
    assert.ok(!formatAxisValue('count', 1500).includes('$'))
  })

  test('a proportion reads as a percentage and a rate does not', () => {
    assert.equal(formatAxisValue('proportion', 0.42), '42%')
    assert.equal(formatAxisValue('rate', 1.83), '1.83')
    // The real misreport this encoding exists to prevent: 1.83
    // memberships per person once appeared as 183%.
    assert.ok(!formatAxisValue('rate', 1.83).includes('%'))
  })

  test('a tooltip and a metric card write the same amount the same way', () => {
    // Deliberately the page's own formatter, whole dollars and all.
    // A chart that showed $123.45 beside a card showing $123 would be
    // two surfaces disagreeing about one number, which is the whole
    // thing this reporting layer exists to prevent.
    assert.equal(formatExactValue('money_cents', 123_45), formatMoney(123_45))
    assert.equal(formatExactValue('count', 1500), '1,500')
  })

  test('an exact count is unabbreviated, unlike its axis label', () => {
    assert.equal(formatExactValue('count', 1500), '1,500')
    assert.equal(formatAxisValue('count', 1500), '1.5k')
  })
})

describe('the chart describes itself for a reader who cannot see it', () => {
  test('the description names direction and both endpoints', () => {
    const s = series({
      points: [
        point({ label: 'Aug', value: 10 }),
        point({ label: 'Sep', value: 40 }),
      ],
    })
    const text = describeSeries(s)
    assert.match(text, /rising/)
    assert.match(text, /10 \(Aug\)/)
    assert.match(text, /40 \(Sep\)/)
  })

  test('a falling series is not described as rising', () => {
    const s = series({
      points: [point({ value: 40 }), point({ value: 10 })],
    })
    assert.match(describeSeries(s), /falling/)
  })

  test('a flat series is described as flat', () => {
    const s = series({ points: [point({ value: 7 }), point({ value: 7 })] })
    assert.match(describeSeries(s), /flat/)
  })

  test('gaps are counted in the description rather than glossed over', () => {
    const s = series({
      points: [
        point({ value: 10 }),
        point({ available: false, value: null }),
        point({ value: 30 }),
      ],
    })
    assert.match(describeSeries(s), /1 of 3 periods have no figure/)
  })

  test('an empty series says so instead of describing nothing', () => {
    const s = series({ points: [point({ available: false, value: null })] })
    assert.match(describeSeries(s), /no figures available/)
  })
})

describe('the chart palette', () => {
  test('is the four Fresh Collective hues, in a fixed order', () => {
    assert.deepEqual([...CHART_HUES], ['teal', 'navy', 'gold', 'watermelon'])
  })

  test('carries the exact hexes that passed the palette validator', () => {
    // Re-stepping any of these invalidates the colour-vision
    // separation that was measured, so the values are pinned:
    //   node scripts/validate_palette.js \
    //     "#0E9A95,#071824,#D4B048,#DC6F5C" --mode light --surface "#FFFFFF"
    //
    // That run reports two FAILs, both against #071824 and both
    // asking whether it is a legible *mid-tone* hue — it is not, and
    // is not meant to be. The checks that decide whether a reader can
    // tell the four apart (CVD separation, normal-vision floor) pass
    // with it, and the worst pair in the palette does not involve
    // navy. See the note on HUE_MARK.navy.
    assert.deepEqual(HUE_STROKE, {
      teal: '#0E9A95',
      navy: '#071824',
      gold: '#D4B048',
      watermelon: '#DC6F5C',
    })
  })

  test('every hue traces to a Fresh Collective token or named colour', () => {
    // The point of the pass: World Insights should look like part of
    // the platform. Gold and watermelon are the token values exactly;
    // teal and navy are chart-strength steps of the same hues, because
    // the token values fall below the chroma floor a data mark needs.
    assert.equal(HUE_STROKE.gold, '#D4B048', 'the Fresh Collective gold')
    assert.equal(HUE_STROKE.watermelon, '#DC6F5C', '--fc-type-video coral')
    assert.equal(
      HUE_STROKE.navy,
      CARD.surface,
      'the chart navy is --fc-surface-inverse itself, not a near miss',
    )
  })

  test('no chart hue is also a status colour', () => {
    // Watermelon is an ordinary series colour now, so a genuine
    // warning must not be drawn in anything a series uses.
    const marks = new Set(Object.values(HUE_STROKE).map((h) => h.toUpperCase()))
    for (const role of Object.values(STATUS)) {
      assert.ok(
        !marks.has(role.fg.toUpperCase()),
        `${role.fg} is both a status and a series colour`,
      )
    }
  })

  test('every hue has a stroke, so a series can never fall back to none', () => {
    for (const hue of CHART_HUES) {
      assert.match(HUE_STROKE[hue], /^#[0-9a-f]{6}$/i)
    }
  })
})

describe('the charts are one component, used many times', () => {
  const CHART = 'src/components/admin/insights/charts/TimeSeriesChart.tsx'
  const PAGES = [
    'src/app/admin/insights/growth/page.tsx',
    'src/app/admin/insights/money/page.tsx',
  ]

  test('both pages draw through the shared panel, not their own SVG', () => {
    for (const path of PAGES) {
      const src = read(path)
      assert.ok(src.includes('<HistoryPanel'), `${path} should use HistoryPanel`)
      assert.ok(
        !/<svg/.test(withoutDocComments(src)),
        `${path} must not hand-roll a chart`,
      )
    }
  })

  test('there is exactly one chart implementation', () => {
    const files = read(CHART)
    assert.ok(files.includes("kind === 'line'"))
    assert.ok(files.includes("kind === 'column'"))
    assert.ok(files.includes("kind === 'stacked'"))
  })

  test('the chart is reachable by keyboard and announces what it shows', () => {
    const src = read(CHART)
    assert.ok(src.includes('tabIndex={0}'), 'the plot must be focusable')
    assert.match(src, /ArrowRight/, 'arrow keys must move through periods')
    assert.match(src, /aria-live="polite"/, 'the active period must be announced')
    assert.match(src, /role="img"/)
    assert.match(src, /aria-describedby/)
  })

  test('every chart offers the figures as a table', () => {
    // The relief the palette requires for a hue below 3:1 against
    // white, and the only way to read exact values without sight.
    const panel = read('src/components/admin/insights/HistoryPanel.tsx')
    assert.ok(panel.includes('showTable'))
    assert.match(panel, /Show the figures/)
  })

  test('the pages do no money arithmetic of their own', () => {
    for (const path of PAGES) {
      const src = read(path)
      assert.ok(
        !/_cents'\)[^)]*\)?\s*[-+*/]\s*pick\(/.test(src),
        `${path} must not do arithmetic between money metrics`,
      )
    }
  })

  test('Growth defaults to production and Money to the whole ledger', () => {
    // Not a preference. A money page defaulting to a subset would
    // misstate the business; a growth page counting test accounts
    // would misstate the communities.
    const growth = read(PAGES[0])
    const money = read(PAGES[1])
    assert.match(growth, /useState<PopulationKey>\('production'\)/)
    assert.match(money, /useState<PopulationKey>\('all'\)/)
  })

  test('both charts and cards resolve their periods through the backend', () => {
    const controls = read('src/components/admin/insights/HistoryControls.tsx')
    // The options come from the response, so a reporting class added
    // later needs no second list here.
    assert.match(controls, /options\?\.ranges/)
    assert.match(controls, /options\?\.populations/)
  })
})

describe('the chart stays inside its card at any width', () => {
  test('the final tick never lands next to its neighbour', () => {
    // The collision this prevents: thinning 13 weekly buckets to three
    // labels put "12 Oct" and "26 Oct" on top of each other at 420px.
    for (const count of [7, 11, 13, 17, 23, 31, 52, 92, 365]) {
      for (const maxLabels of [2, 3, 4, 6, 8]) {
        const ticks = xTickIndices(count, maxLabels)
        const stride = Math.ceil(count / maxLabels)
        for (let i = 1; i < ticks.length; i += 1) {
          assert.ok(
            ticks[i] - ticks[i - 1] >= stride,
            `count=${count} max=${maxLabels} ticks=${ticks} collide at ${i}`,
          )
        }
      }
    }
  })

  test('the first and last period survive the collision fix', () => {
    for (const count of [13, 31, 92]) {
      const ticks = xTickIndices(count, 3)
      assert.equal(ticks[0], 0)
      assert.equal(ticks[ticks.length - 1], count - 1)
    }
  })

  test('direct labels are dropped on a narrow chart rather than clipped', () => {
    const src = read('src/components/admin/insights/charts/TimeSeriesChart.tsx')
    // The space is measured from the names that go in it, and the
    // label is drawn in full or not at all — there is no abbreviator
    // left to truncate with.
    assert.match(src, /directLabelSpace\(/)
    assert.ok(!/abbreviate/.test(src), 'labels must never be abbreviated')
    // Nothing may paint outside the SVG box either way.
    assert.match(src, /overflow: 'hidden'/)
  })

  test('labels that would overlap are pushed apart, in order', () => {
    const ys = spreadLabels([100, 104, 108], 13, [0, 200])
    assert.ok(ys[1] - ys[0] >= 13)
    assert.ok(ys[2] - ys[1] >= 13)
    // Stable: the series that was highest stays highest.
    assert.ok(ys[0] < ys[1] && ys[1] < ys[2])
  })

  test('spreading never pushes a label out of the plot', () => {
    const ys = spreadLabels([190, 195, 199], 13, [0, 200])
    for (const y of ys) {
      assert.ok(y >= 0 && y <= 200, `${y} is outside the plot`)
    }
  })

  test('labels already far apart are left where they are', () => {
    assert.deepEqual(spreadLabels([20, 80, 150], 13, [0, 200]), [20, 80, 150])
  })

  test('a single label needs no spreading', () => {
    assert.deepEqual(spreadLabels([42], 13, [0, 200]), [42])
    assert.deepEqual(spreadLabels([], 13, [0, 200]), [])
  })
})

describe('what stays on screen and what moves behind a disclosure', () => {
  test('the panel offers the disclosure and keeps the table at top level', () => {
    const panel = read('src/components/admin/insights/HistoryPanel.tsx')
    assert.match(panel, /What does this chart mean\?/)
    // A controlled disclosure: a button carrying aria-expanded and
    // aria-controls, which announces as one and can be laid out beside
    // the table control. A details/summary could not be, without
    // nesting a second interactive control inside the summary.
    assert.match(panel, /aria-expanded=\{showMeaning\}/)
    assert.match(panel, /aria-controls=\{meaningId\}/)
    assert.ok(
      !/<summary/.test(panel),
      'a button must not be nested inside a summary element',
    )
  })

  test('the table control is a peer of the disclosure, not inside it', () => {
    // The table is the palette's required relief for a hue below 3:1
    // against white; burying it one level deeper than the explanation
    // would make the required thing harder to reach than the optional
    // one.
    const panel = read('src/components/admin/insights/HistoryPanel.tsx')
    const meaningPanel = panel.indexOf('{showMeaning && (')
    const tableControl = panel.indexOf('Show the figures')
    assert.ok(tableControl < meaningPanel, 'the table control must come first')
  })

  test('the registry limitations still reach the page, just not inline', () => {
    const panel = read('src/components/admin/insights/HistoryPanel.tsx')
    assert.match(panel, /s\.limitations/, 'limitations must still be rendered')
    assert.match(panel, /source_of_truth/, 'the source must be shown')
  })
})

describe('the charts lead each page and the cards follow', () => {
  const PAGES = [
    'src/app/admin/insights/growth/page.tsx',
    'src/app/admin/insights/money/page.tsx',
  ]

  test('the first chart appears before the first metric card', () => {
    for (const path of PAGES) {
      const src = read(path)
      const firstChart = src.indexOf('<HistoryPanel')
      const firstCard = src.indexOf('<InsightCard')
      assert.ok(firstChart > 0 && firstCard > 0, path)
      assert.ok(
        firstChart < firstCard,
        `${path}: the charts should lead the page`,
      )
    }
  })

  test('the history controls sit above the first chart', () => {
    for (const path of PAGES) {
      const src = read(path)
      assert.ok(
        src.indexOf('<HistoryControls') < src.indexOf('<HistoryPanel'),
        `${path}: the filters must be reachable before the charts`,
      )
    }
  })

  test('the period control still governs the cards it sits with', () => {
    for (const path of PAGES) {
      const src = read(path)
      // It moved down the page with the cards, but it must still be
      // between the charts and the first card rather than orphaned.
      const period = src.indexOf('<PeriodSelect')
      assert.ok(period > src.indexOf('<HistoryPanel'), path)
      assert.ok(period < src.indexOf('<InsightCard'), path)
    }
  })

  test('exactly one chart per page is the prominent one', () => {
    for (const path of PAGES) {
      const matches = [...read(path).matchAll(/\bprominent\b/g)]
      assert.equal(matches.length, 1, `${path} should have one lead chart`)
    }
  })

  test('Growth leads with membership growth, Money with its own income', () => {
    const growth = read(PAGES[0])
    const money = read(PAGES[1])
    assert.match(
      growth.slice(growth.indexOf('<HistoryPanel'), growth.indexOf('<HistoryPanel') + 400),
      /Membership growth/,
    )
    assert.match(
      money.slice(money.indexOf('<HistoryPanel'), money.indexOf('<HistoryPanel') + 400),
      /Fresh Collective's own income/,
    )
  })

  test('the Money page still groups the cards by whose money it is', () => {
    const money = read(PAGES[1])
    for (const band of [
      "Fresh Collective's own income",
      'Money we moved for creators',
      'Money that went back',
    ]) {
      assert.ok(money.includes(band), `${band} should still be a band`)
    }
    // Ownership order preserved: ours, then creators', then returned.
    const ours = money.lastIndexOf("Fresh Collective's own income")
    const theirs = money.indexOf('Money we moved for creators')
    const back = money.indexOf('Money that went back')
    assert.ok(ours < theirs && theirs < back)
  })

  test('the reconciliation detail is still on the Money page', () => {
    const money = read(PAGES[1])
    assert.ok(money.includes('<WhoIsOwedNote'))
    assert.ok(money.includes('<WhoseMoneyNote'))
    assert.ok(money.includes('<NotProfitNote'))
  })

  test('no metric card was dropped in the rearrangement', () => {
    // The reorder must not have quietly lost a figure.
    const growth = read(PAGES[0])
    const money = read(PAGES[1])
    for (const key of [
      'unique_members', 'total_memberships', 'memberships_per_member',
      'multi_collective_members', 'registered_users', 'registered_creators',
      'total_collectives', 'active_collectives', 'memberships_started',
    ]) {
      assert.ok(growth.includes(`pick(data, '${key}')`), `growth lost ${key}`)
    }
    for (const key of [
      'platform_fee_revenue_cents', 'subscription_revenue_cents',
      'processing_costs_cents', 'contribution_after_processing_cents',
      'gross_collective_sales_cents', 'creator_earnings_cents',
      'paid_out_cents', 'outstanding_payouts_cents', 'refunds_cents',
    ]) {
      assert.ok(money.includes(`pick(data, '${key}')`), `money lost ${key}`)
    }
  })
})

describe('a direct label is drawn in full or not at all', () => {
  test('the reserved space fits the longest name', () => {
    const names = ['Unique members', 'Collective memberships']
    const { show, padRight } = directLabelSpace(names, 1058)
    assert.ok(show)
    const widest = Math.max(...names.map((n) => estimateTextWidth(n, 11)))
    assert.ok(
      padRight >= widest,
      `reserved ${padRight}px for a ${widest.toFixed(0)}px label`,
    )
  })

  test('a name too long for the chart drops the labels rather than cutting them', () => {
    const { show, padRight } = directLabelSpace(
      ['Contribution after processing costs for the period'],
      700,
    )
    assert.equal(show, false)
    assert.equal(padRight, 12)
  })

  test('labels are all shown or all hidden, never some of each', () => {
    // One short name and one very long one: reserving for the short
    // one would truncate the long one, so neither is drawn.
    const { show } = directLabelSpace(
      ['Paid out', 'Creator earnings before refunds and adjustments applied'],
      620,
    )
    assert.equal(show, false)
  })

  test('a narrow chart never spends more than its share on labels', () => {
    for (const width of [360, 420, 560, 760, 1100]) {
      const { show, padRight } = directLabelSpace(
        ['Platform fee revenue', 'Creator subscriptions'],
        width,
      )
      if (show) {
        assert.ok(
          padRight <= width * 0.28 + 1,
          `${width}px chart gave ${padRight}px to labels`,
        )
        assert.ok(width - padRight > 220, 'the plot must stay usable')
      }
    }
  })

  test('a single series needs no direct label at all', () => {
    assert.deepEqual(directLabelSpace(['Refunds'], 1000), {
      show: false,
      padRight: 12,
    })
  })

  test('text width grows with length and with wide letters', () => {
    assert.ok(estimateTextWidth('WWWW', 11) > estimateTextWidth('iiii', 11))
    assert.ok(estimateTextWidth('aaaaaaaa', 11) > estimateTextWidth('aaaa', 11))
    assert.equal(estimateTextWidth('', 11), 0)
  })
})

describe('the axis reserves what its own labels need', () => {
  test('a money axis gets more room than a small count axis', () => {
    const money = axisLabelSpace(['$0', '$500', '$1k', '$1.5k', '$2.5m'])
    const counts = axisLabelSpace(['0', '10', '20', '30', '40'])
    assert.ok(money > counts, 'currency labels are wider and must fit')
  })

  test('there is always room for something', () => {
    assert.ok(axisLabelSpace([]) >= 28)
  })

  test('the widest tick decides, not the last one', () => {
    assert.equal(
      axisLabelSpace(['$1.25m', '$1']),
      axisLabelSpace(['$1', '$1.25m']),
    )
  })
})

describe('the tooltip stays inside the chart at any width', () => {
  test('it sits beside the point when there is room', () => {
    assert.equal(tooltipLeft(100, 1000, 250, 12), 112)
  })

  test('it moves to the other side rather than overflowing the right', () => {
    const left = tooltipLeft(950, 1000, 250, 12)
    assert.ok(left + 250 <= 1000, 'the tooltip ran off the right edge')
  })

  test('it never overflows either edge, at any point on any width', () => {
    for (const width of [320, 390, 768, 1200]) {
      const box = Math.min(250, Math.max(140, width - 16))
      for (let x = 0; x <= width; x += 10) {
        const left = tooltipLeft(x, width, box)
        assert.ok(left >= 0, `x=${x} w=${width} left=${left}`)
        assert.ok(left + box <= width, `x=${x} w=${width} overflowed right`)
      }
    }
  })

  test('a chart narrower than the tooltip still places it at zero', () => {
    assert.equal(tooltipLeft(50, 200, 250), 0)
  })
})

describe('reconstructed is not a synonym for doubtful', () => {
  const sound = (over = {}) =>
    series({ availability: 'full', ...over })
  const shaky = (over = {}) =>
    series({ availability: 'partial', ...over })

  test('a reconstruction from sufficient records is not a caution', () => {
    const s = sound({ points: [point({ provenance: 'reconstructed' })] })
    assert.equal(pointQuality(s.points[0], s), 'reconstructed')
    const notes = historyQuality([s])
    assert.ok(notes.every((n) => !n.caution), 'a sound reconstruction is a fact')
  })

  test('a reconstruction the records cannot support is a caution', () => {
    const s = shaky({ points: [point({ provenance: 'reconstructed' })] })
    assert.equal(pointQuality(s.points[0], s), 'limited')
    assert.ok(historyQuality([s]).some((n) => n.caution))
  })

  test('the two are told apart by availability, not by provenance', () => {
    // The whole point: same provenance, different registry metadata,
    // different reading. Nothing here is a frontend assumption.
    const p = point({ provenance: 'reconstructed' })
    assert.notEqual(
      pointQuality(p, sound({ points: [p] })),
      pointQuality(p, shaky({ points: [p] })),
    )
  })

  test('a recorded figure is observed however late it was written down', () => {
    const s = sound({ points: [point({ provenance: 'observed_late' })] })
    assert.equal(pointQuality(s.points[0], s), 'observed')
  })

  test('a missing figure is unavailable, whatever else is true of it', () => {
    const s = shaky({
      points: [point({ available: false, value: null, provenance: null })],
    })
    assert.equal(pointQuality(s.points[0], s), 'unavailable')
  })

  test('a part period outranks its provenance', () => {
    const s = sound({ points: [point({ partial_data: true })] })
    assert.equal(pointQuality(s.points[0], s), 'incomplete')
  })

  test('an entirely observed chart says nothing at all', () => {
    assert.deepEqual(historyQuality([sound()]), [])
  })

  test('an entirely reconstructed chart says nothing either', () => {
    const s = sound({
      points: [
        point({ provenance: 'reconstructed' }),
        point({ provenance: 'reconstructed' }),
      ],
    })
    assert.deepEqual(historyQuality([s]), [])
  })

  test('a mixed chart names each kind present, and only those', () => {
    const s = sound({
      points: [
        point({ provenance: 'observed' }),
        point({ provenance: 'reconstructed' }),
        point({ available: false, value: null }),
      ],
    })
    const kinds = historyQuality([s]).map((q) => q.kind)
    assert.deepEqual([...kinds].sort(), ['observed', 'reconstructed', 'unavailable'])
    assert.ok(!kinds.includes('limited'))
    assert.ok(!kinds.includes('incomplete'))
  })

  test('cautions are listed before statements of fact', () => {
    const s = shaky({
      points: [
        point({ provenance: 'observed' }),
        point({ available: false, value: null }),
      ],
    })
    const notes = historyQuality([s])
    const firstFact = notes.findIndex((n) => !n.caution)
    const lastCaution = notes.map((n) => n.caution).lastIndexOf(true)
    assert.ok(lastCaution < firstFact || firstFact === -1)
  })

  test('each note counts the periods it describes', () => {
    const s = sound({
      points: [
        point(),
        point(),
        point({ available: false, value: null }),
      ],
    })
    const gap = historyQuality([s]).find((q) => q.kind === 'unavailable')
    assert.match(gap?.text ?? '', /1 of 3 periods/)
  })

  test('periods are counted once however many series the chart has', () => {
    // Two series over three periods is six points and three periods.
    // "1 of 6 periods" describes something the reader cannot see.
    const a = sound({ points: [point(), point(), point({ available: false, value: null })] })
    const b = sound({ key: 'b', points: [point(), point(), point({ available: false, value: null })] })
    const notes = historyQuality([a, b])
    assert.match(notes.find((q) => q.kind === 'unavailable')?.text ?? '', /1 of 3 periods/)
    assert.match(notes.find((q) => q.kind === 'observed')?.text ?? '', /2 of 3 periods/)
  })

  test('the counts sum to the number of periods on the axis', () => {
    const a = sound({
      points: [point(), point({ provenance: 'reconstructed' }),
               point({ available: false, value: null }), point({ partial_data: true })],
    })
    const counted = historyQuality([a])
      .map((q) => Number(/(\d+) of/.exec(q.text)?.[1] ?? 0))
      .reduce((x, y) => x + y, 0)
    assert.equal(counted, 4)
  })

  test('a gap in one series is not hidden by an observation in another', () => {
    // Surfaced as coverage rather than as "unavailable": the period
    // is not unknown, one of the series simply has no figure for it.
    // Either way the reader is told — silence was the failure.
    const a = sound({ points: [point({ available: false, value: null })] })
    const b = sound({ key: 'b', points: [point()] })
    const notes = historyQuality([a, b])
    assert.ok(notes.some((q) => q.kind === 'coverage'))
    assert.ok(notes.some((q) => q.caution), 'and flagged as a caution')
  })

  test('every kind has a label a reader can read', () => {
    for (const kind of [
      'observed', 'reconstructed', 'limited', 'incomplete', 'unavailable',
      'coverage',
    ] as const) {
      assert.ok(QUALITY_LABEL[kind], `no label for ${kind}`)
    }
  })

  test('an emptied classification filter is still a caution', () => {
    const s = series({
      qualifiers: { population_empty_note: 'No settled member purchases here.' },
    })
    assert.deepEqual(populationNotes([s]), ['No settled member purchases here.'])
  })

  test('a tooltip calls a sound reconstruction exact, not doubtful', () => {
    const s = sound({ points: [point({ provenance: 'reconstructed' })] })
    const notes = pointCaveats(s.points[0], s)
    assert.ok(notes.some((n) => /exact, not an estimate/.test(n)))
    assert.ok(!notes.some((n) => /may be incomplete/.test(n)))
  })

  test('a tooltip warns where the records cannot support the figure', () => {
    const s = shaky({ points: [point({ provenance: 'reconstructed' })] })
    assert.ok(
      pointCaveats(s.points[0], s).some((n) => /may make this incomplete/.test(n)),
    )
  })

  test('the panel marks cautions and facts differently', () => {
    const panel = read('src/components/admin/insights/HistoryPanel.tsx')
    assert.match(panel, /QualityLine/)
    // Filled marker for a caution, hollow for a fact — shape as well as
    // colour, and the leading word carries it in text regardless.
    assert.match(panel, /caution \? '\\u25cf' : '\\u25cb'/)
    assert.match(panel, /QUALITY_LABEL\[note\.kind\]/)
  })

  test('the four kinds are defined in the disclosure', () => {
    const panel = read('src/components/admin/insights/HistoryPanel.tsx')
    assert.match(panel, /How this history was established/)
    for (const label of [
      'Observed', 'Reconstructed', 'Historical limitation', 'Unavailable',
    ]) {
      assert.ok(panel.includes(`label="${label}"`), `${label} is not defined`)
    }
  })
})

describe('two charts on one page share an axis density', () => {
  test('capacity comes from the labels, not from the space left over', () => {
    // The bug: one panel reserved more room for long series names, so
    // its plot was narrower and it thinned its dates while the panel
    // above it did not. Same page, same range, two different axes.
    const labels = ['3 Aug', '10 Aug', '17 Aug', '24 Aug', '31 Aug']
    const wide = xLabelCapacity(labels, 860)
    const slightlyNarrower = xLabelCapacity(labels, 820)
    assert.equal(
      Math.min(wide, labels.length),
      Math.min(slightlyNarrower, labels.length),
      'a 40px difference in plot width must not change the axis',
    )
  })

  test('thirteen weekly dates fit a desktop plot either way', () => {
    const labels = Array.from({ length: 13 }, (_, i) => `${i + 1} Oct`)
    for (const plotW of [780, 820, 860, 900]) {
      assert.ok(
        xLabelCapacity(labels, plotW) >= 13,
        `${plotW}px should fit 13 dates`,
      )
    }
  })

  test('a narrow plot still thins rather than colliding', () => {
    const labels = Array.from({ length: 13 }, (_, i) => `${i + 1} Oct`)
    const capacity = xLabelCapacity(labels, 240)
    assert.ok(capacity < 13)
    const ticks = xTickIndices(13, capacity)
    const widest = Math.max(...labels.map((l) => estimateTextWidth(l, 12)))
    const band = 240 / 13
    for (let i = 1; i < ticks.length; i += 1) {
      assert.ok(
        (ticks[i] - ticks[i - 1]) * band >= widest,
        `labels ${ticks[i - 1]} and ${ticks[i]} would collide`,
      )
    }
  })

  test('longer labels get fewer of them', () => {
    const short = xLabelCapacity(['Jan', 'Feb', 'Mar'], 600)
    const long = xLabelCapacity(['w/c 2026-10-05', 'w/c 2026-10-12'], 600)
    assert.ok(short > long)
  })

  test('an empty axis still reports a usable capacity', () => {
    assert.ok(xLabelCapacity([], 600) >= 2)
  })
})

describe('comparing Collectives without flattering the new ones', () => {
  const at = (values: (number | null)[], over: Partial<HistoryPoint> = {}) =>
    values.map((v, i) => point({
      label: `p${i}`,
      value: v,
      available: v !== null,
      unavailable_reason: v === null ? 'No figure.' : null,
      complete: true,
      clipped: false,
      ...over,
    }))

  const coll = (id: string, name: string, values: (number | null)[]) =>
    series({ key: 'unique_members', collective_id: id, collective_name: name,
             points: at(values) })

  test('a standing carries the first and last figure and the change', () => {
    const [s] = collectiveStandings([coll('a', 'EMBODY', [10, 12, 14, 20])])
    assert.equal(s.collectiveName, 'EMBODY')
    assert.equal(s.earliest, 10)
    assert.equal(s.latest, 20)
    assert.equal(s.change, 10)
    assert.equal(s.changePct, 1)
    assert.ok(s.comparable)
  })

  test('platform series are not standings', () => {
    assert.deepEqual(collectiveStandings([series()]), [])
  })

  test('largest is ranked on the current figure', () => {
    const { ranked } = bySize([
      coll('a', 'A', [1, 2, 3, 50]),
      coll('b', 'B', [90, 90, 90, 90]),
    ].flatMap((s) => collectiveStandings([s])))
    assert.deepEqual(ranked.map((r) => r.collectiveName), ['B', 'A'])
  })

  test('a young Collective is still ranked by size', () => {
    // Being small and new is a fact about it, not a distortion.
    const young = collectiveStandings([coll('a', 'New', [null, null, null, 4])])
    const { ranked, withheld } = bySize(young)
    assert.equal(ranked.length, 1)
    assert.equal(withheld.length, 0)
  })

  test('a young Collective is NOT ranked on growth', () => {
    // One member to two is a 100% rise and would top the table.
    const young = collectiveStandings([coll('a', 'New', [null, null, null, 2])])
    const { ranked, withheld } = byGrowth(young)
    assert.equal(ranked.length, 0)
    assert.equal(withheld.length, 1)
    assert.match(withheld[0].reason ?? '', /too few to compare/)
  })

  test('the reason distinguishes limited history from poor performance', () => {
    const [s] = collectiveStandings([coll('a', 'New', [null, null, 1, 2])])
    assert.ok(!s.comparable)
    assert.ok(/history/i.test(s.reason ?? ''), s.reason ?? 'no reason given')
  })

  test('a Collective with no figures at all says so', () => {
    const [s] = collectiveStandings([coll('a', 'Empty', [null, null, null, null])])
    assert.equal(s.latest, null)
    assert.equal(s.reason, 'No figures in this range.')
    assert.equal(bySize([s]).ranked.length, 0)
    assert.equal(bySize([s]).withheld.length, 1)
  })

  test('nothing is silently dropped — every Collective is ranked or explained', () => {
    const all = [
      coll('a', 'Established', [10, 12, 14, 20]),
      coll('b', 'New', [null, null, null, 3]),
      coll('c', 'Empty', [null, null, null, null]),
    ].flatMap((s) => collectiveStandings([s]))
    for (const { ranked, withheld } of [bySize(all), byGrowth(all)]) {
      assert.equal(ranked.length + withheld.length, 3)
    }
  })

  test('growth ranks largest increase first and quietening the reverse', () => {
    const all = [
      coll('a', 'Up', [10, 12, 14, 30]),
      coll('b', 'Down', [40, 30, 25, 20]),
      coll('c', 'Flat', [5, 5, 5, 5]),
    ].flatMap((s) => collectiveStandings([s]))
    assert.deepEqual(
      byGrowth(all, 'up').ranked.map((r) => r.collectiveName),
      ['Up', 'Flat', 'Down'],
    )
    assert.deepEqual(
      byGrowth(all, 'down').ranked.map((r) => r.collectiveName),
      ['Down', 'Flat', 'Up'],
    )
  })

  test('only a genuine fall counts as quietening', () => {
    const [up] = collectiveStandings([coll('a', 'Up', [1, 2, 3, 9])])
    const [flat] = collectiveStandings([coll('b', 'Flat', [5, 5, 5, 5])])
    const [down] = collectiveStandings([coll('c', 'Down', [9, 6, 4, 1])])
    assert.equal(isQuietening(up), false)
    assert.equal(isQuietening(flat), false)
    assert.equal(isQuietening(down), true)
  })

  test('an unfinished period never decides the direction', () => {
    // A half-finished week is three days against seven; reading it as
    // the endpoint turns every Collective into a collapsing one.
    const points = [
      ...at([10, 12, 14, 16]),
      point({ label: 'p4', value: 2, complete: false }),
    ]
    const [s] = collectiveStandings([
      series({ collective_id: 'a', collective_name: 'A', points }),
    ])
    assert.equal(s.latest, 16, 'the last complete period decides')
    assert.ok((s.change as number) > 0)
  })

  test('a zero starting point does not produce an infinite percentage', () => {
    const [s] = collectiveStandings([coll('a', 'A', [0, 1, 2, 3])])
    assert.equal(s.change, 3)
    assert.equal(s.changePct, null, 'no percentage from a zero base')
  })

  test('the comparison threshold is stated, not hidden', () => {
    assert.ok(MIN_COMPARABLE_PERIODS >= 2)
    const table = read('src/components/admin/insights/StandingsTable.tsx')
    assert.match(table, /MIN_COMPARABLE_PERIODS/)
    assert.match(table, /Limited history, not poor performance/)
  })
})

describe('the Collectives page', () => {
  const PAGE = 'src/app/admin/insights/collectives/page.tsx'

  test('leads with charts and puts the cards underneath', () => {
    const src = read(PAGE)
    assert.ok(src.indexOf('<HistoryControls') < src.indexOf('<HistoryPanel'))
    assert.ok(src.indexOf('<HistoryPanel') < src.indexOf('<InsightCard'))
  })

  test('defaults to Production, like Growth', () => {
    assert.match(read(PAGE), /useState<PopulationKey>\('production'\)/)
  })

  test('compares no more Collectives than the palette has hues', () => {
    // A fifth line would repeat a colour, which is indistinguishable
    // from one line.
    const src = read(PAGE)
    assert.match(src, /MAX_COMPARED = CHART_HUES\.length/)
  })

  test('it introduces no blended engagement score', () => {
    const src = withoutDocComments(read(PAGE))
    // The measures must stay separate: no arithmetic combining one
    // participation metric with another.
    assert.ok(
      !/participation_acts'\)[^)]*\)?\s*[-+*/]\s*pick\(/.test(src),
      'participation measures must not be combined',
    )
    assert.ok(!/engagementScore|blendedScore|overallScore/i.test(src))
  })

  test('the themes breakdown is read from the metric, not recomputed', () => {
    const src = read(PAGE)
    assert.match(src, /active_members_by_theme/)
    assert.match(src, /multi-select/, 'the double-counting must be disclosed')
  })

  test('it reuses the shared chart and control components', () => {
    const src = read(PAGE)
    for (const component of [
      '<HistoryPanel', '<HistoryControls', '<PeriodSelect',
      '<CollectiveSelect', '<StandingsTable', '<InsightCard',
    ]) {
      assert.ok(src.includes(component), `${component} should be reused`)
    }
    assert.ok(!/<svg/.test(withoutDocComments(src)), 'no hand-rolled chart')
  })

  test('every compared metric can actually be broken down per Collective', () => {
    // A platform-only metric would draw one identical line per
    // Collective; the backend returns a gap instead, but the page
    // should not be asking in the first place.
    const src = read(PAGE)
    const keys = /const COMPARISON_KEYS = \[([\s\S]*?)\]/.exec(src)?.[1] ?? ''
    for (const forbidden of [
      'subscription_revenue_cents',
      'registered_users',
      'contribution_after_processing_cents',
    ]) {
      assert.ok(!keys.includes(forbidden), `${forbidden} is platform-level`)
    }
  })
})

describe('comparing series that begin at different times', () => {
  const pts = (values: (number | null)[]) =>
    values.map((v, i) => point({
      label: `p${i}`, value: v, available: v !== null,
      unavailable_reason: v === null ? 'No figure.' : null,
    }))

  test('a key is unique across a comparison', () => {
    // Four Collectives on one metric all carry the same metric key;
    // React reusing one chart component's state for another's data
    // shows the wrong Collective in a tooltip.
    const a = series({ collective_id: 'c1' })
    const b = series({ collective_id: 'c2' })
    assert.notEqual(seriesKey(a), seriesKey(b))
    assert.equal(seriesKey(series()), 'unique_members')
  })

  test('a period is only unavailable when nothing at all is known', () => {
    // The old rule said "9 of 13 periods cannot be established" over a
    // chart drawing one blank band, because a Collective that opened
    // in September has no August.
    const established = series({ collective_id: 'c1', points: pts([1, 2, 3]) })
    const newcomer = series({
      key: 'unique_members', collective_id: 'c2', points: pts([null, null, 3]),
    })
    const gap = historyQuality([established, newcomer]).find(
      (q) => q.text.includes('cannot be established'),
    )
    assert.equal(gap, undefined, 'no period here is wholly unknown')
  })

  test('a period nobody has a figure for is still unavailable', () => {
    const a = series({ collective_id: 'c1', points: pts([1, null, 3]) })
    const b = series({ key: 'unique_members', collective_id: 'c2', points: pts([2, null, 4]) })
    const gap = historyQuality([a, b]).find((q) => q.text.includes('cannot be established'))
    assert.match(gap?.text ?? '', /1 of 3/)
  })

  test('partial coverage is reported as its own thing', () => {
    const established = series({ collective_id: 'c1', points: pts([1, 2, 3]) })
    const newcomer = series({
      key: 'unique_members', collective_id: 'c2', points: pts([null, null, 3]),
    })
    const note = historyQuality([established, newcomer]).find(
      (q) => q.kind === 'coverage',
    )
    assert.ok(note, 'a reader must be told some lines start later')
    assert.match(note!.text, /2 of 3 periods/)
    assert.match(note!.text, /not the same as a fall to nothing/)
    assert.equal(QUALITY_LABEL.coverage, 'Shorter history')
    assert.notEqual(
      QUALITY_LABEL.coverage, QUALITY_LABEL.unavailable,
      'two different facts must not share a label',
    )
  })

  test('the note matches what the chart actually shades', () => {
    // emptyBucketIndices decides the hatched bands; the unavailable
    // count must agree with it or the words contradict the picture.
    const a = series({ collective_id: 'c1', points: pts([1, null, 3]) })
    const b = series({ key: 'unique_members', collective_id: 'c2', points: pts([null, null, 4]) })
    const shaded = emptyBucketIndices([a, b]).length
    const stated = historyQuality([a, b]).find((q) =>
      q.text.includes('cannot be established'),
    )
    assert.equal(shaded, 1)
    assert.match(stated?.text ?? '', new RegExp(`${shaded} of 3`))
  })

  test('fully covered series need no coverage note', () => {
    const a = series({ collective_id: 'c1', points: pts([1, 2, 3]) })
    const b = series({ key: 'unique_members', collective_id: 'c2', points: pts([4, 5, 6]) })
    assert.deepEqual(historyQuality([a, b]), [])
  })
})

describe('the Collectives page says what it is measuring', () => {
  const PAGE = 'src/app/admin/insights/collectives/page.tsx'
  const TABLE = 'src/components/admin/insights/StandingsTable.tsx'

  test('the growth ranking states that it is absolute, not a percentage', () => {
    // "Growing fastest" reads as a rate; the ranking is absolute. The
    // difference changes the order, so it has to be on the card.
    const src = read(TABLE)
    assert.match(src, /absolute number, not a percentage/)
    assert.match(src, /added 40 members ranks above one that doubled/)
  })

  test('the percentage is shown beside the absolute figure', () => {
    const src = read(TABLE)
    assert.match(src, /function percent/)
    assert.match(src, /s\.changePct !== null/)
  })

  test('the ranking titles do not imply a rate', () => {
    // Checked against the TITLES map rather than the whole file: the
    // doc comment beside it explains why "growing fastest" was wrong,
    // and a blunt scan reads the explanation as the offence.
    const src = read(TABLE)
    const titles = /const TITLES[\s\S]*?\n\}/.exec(src)?.[0] ?? ''
    assert.ok(titles, 'could not find the titles')
    assert.ok(!/fastest/i.test(titles), '"fastest" implies a rate')
    assert.match(titles, /Biggest increase/)
  })

  test('the theme counts say they are people, not memberships', () => {
    const src = read(PAGE)
    assert.match(src, /Distinct people/)
    assert.match(src, /not\s*\n?\s*memberships/)
    assert.match(src, /counted once for it/)
    assert.match(src, /not meant to be summed/)
  })

  test('the status cards ask a live question, not a historical one', () => {
    // Status is one column with no history, so a closed period has no
    // honest answer — asking for one put "Not yet" on a card whose
    // heading says "right now".
    const src = read(PAGE)
    assert.match(src, /useMetrics\(STATUS_KEYS, 'all_time', population\)/)
    assert.match(src, /Collectives right now/)
    for (const key of [
      'total_collectives', 'active_collectives',
      'draft_collectives', 'archived_collectives',
    ]) {
      assert.ok(
        new RegExp(`pick\\(status, '${key}'\\)`).test(src),
        `${key} should read from the live fetch`,
      )
    }
  })

  test('the period selector still governs what genuinely varies by period', () => {
    const src = read(PAGE)
    assert.match(src, /useMetrics\(\s*CARD_KEYS, period, population,?\s*\)/)
    const cardKeys = /const CARD_KEYS = \[([\s\S]*?)\]/.exec(src)?.[1] ?? ''
    assert.ok(!cardKeys.includes('collectives'), 'status must not be period-bound')
    assert.ok(cardKeys.includes('engagement_by_theme'))
  })
})

describe('the creator journey is a position, not a score', () => {
  const creator = (over: Partial<Creator> = {}): Creator => ({
    id: 'u1', name: 'Someone', founder_operated: false,
    reporting_class: null, created_at: '2026-01-01', collectives: [],
    first_collective_at: null, stage: 'registered', members: 0,
    earned_cents: 0, ...over,
  })

  test('the stages are declared in one place, in order', () => {
    assert.deepEqual(
      CREATOR_STAGES.map((s) => s.key),
      ['registered', 'building', 'attracting', 'earning'],
    )
  })

  test('reached only ever narrows', () => {
    const counts = stageCounts([
      creator({ id: 'a', stage: 'registered' }),
      creator({ id: 'b', stage: 'building' }),
      creator({ id: 'c', stage: 'attracting' }),
      creator({ id: 'd', stage: 'earning' }),
    ])
    assert.deepEqual(counts.map((c) => c.reached), [4, 3, 2, 1])
  })

  test('at shows where people stopped, and does not narrow', () => {
    const counts = stageCounts([
      creator({ id: 'a', stage: 'building' }),
      creator({ id: 'b', stage: 'building' }),
      creator({ id: 'c', stage: 'earning' }),
    ])
    const at = Object.fromEntries(counts.map((c) => [c.key, c.at]))
    assert.equal(at.registered, 0)
    assert.equal(at.building, 2, 'two creators have stopped at building')
    assert.equal(at.earning, 1)
  })

  test('every creator is counted exactly once across the at counts', () => {
    const people = [
      creator({ id: 'a', stage: 'registered' }),
      creator({ id: 'b', stage: 'building' }),
      creator({ id: 'c', stage: 'building' }),
      creator({ id: 'd', stage: 'earning' }),
    ]
    const total = stageCounts(people).reduce((n, c) => n + c.at, 0)
    assert.equal(total, people.length)
  })

  test('an empty platform produces zeroes rather than nothing', () => {
    const counts = stageCounts([])
    assert.equal(counts.length, CREATOR_STAGES.length)
    assert.ok(counts.every((c) => c.at === 0 && c.reached === 0))
  })

  test('founder-operated is kept apart from independent', () => {
    const { founder, independent } = byOperator([
      creator({ id: 'a', founder_operated: true }),
      creator({ id: 'b', founder_operated: false }),
    ])
    assert.deepEqual(founder.map((c) => c.id), ['a'])
    assert.deepEqual(independent.map((c) => c.id), ['b'])
  })

  test('nobody is dropped by the split', () => {
    const people = [
      creator({ id: 'a', founder_operated: true }),
      creator({ id: 'b' }),
      creator({ id: 'c' }),
    ]
    const { founder, independent } = byOperator(people)
    assert.equal(founder.length + independent.length, people.length)
  })
})

describe('the Creators page', () => {
  const PAGE = 'src/app/admin/insights/creators/page.tsx'
  const JOURNEY = 'src/components/admin/insights/CreatorJourney.tsx'

  test('leads with the journey and puts the cards underneath', () => {
    const src = read(PAGE)
    assert.ok(src.indexOf('<HistoryControls') < src.indexOf('<CreatorJourney'))
    assert.ok(src.indexOf('<CreatorJourney') < src.indexOf('<InsightCard'))
  })

  test('it produces no score and no creator ranking', () => {
    // Checked as code rather than as prose. Both files *say* the words
    // — explaining why there is no ranking is the point — so a scan
    // for them bans the explanation rather than the thing. What must
    // not exist is an identifier holding a computed score, or a sort
    // that orders creators by one.
    const src = read(PAGE) + read(JOURNEY)
    assert.ok(
      !/\b\w*[Ss]core\b\s*[=:]/.test(src),
      'no identifier may hold a creator score',
    )
    assert.ok(
      !/creators[\s\S]{0,40}\.sort\(/.test(src),
      'creators must not be ordered by a computed value',
    )
    // The stage is read straight from the backend and only counted
    // here — the component renders `c.stage`, it does not decide it.
    assert.match(read('src/lib/insights-history.ts'), /c\.stage === stage\.key/)
    assert.match(read(JOURNEY), /\{c\.stage\}/)
  })

  test('independent and founder-operated are separate tables', () => {
    const src = read(JOURNEY)
    assert.match(src, /Independent creators/)
    assert.match(src, /Founder-operated/)
    assert.match(src, /byOperator/)
  })

  test('publishing is explicitly not a funnel stage', () => {
    // spaces.status has no history, so it would be the one step of
    // the funnel nobody could trust.
    assert.ok(
      !CREATOR_STAGES.some((s) => /publish/i.test(s.key + s.label)),
      'publishing cannot be reconstructed and must not be a stage',
    )
    assert.match(read(PAGE), /Publishing is not a stage here/)
  })

  test('status cards ask the live question', () => {
    assert.match(
      read(PAGE),
      /useMetrics\(STATUS_KEYS, 'all_time', population\)/,
    )
  })

  test('it reuses the shared charts and controls', () => {
    const src = read(PAGE)
    for (const c of [
      '<HistoryPanel', '<HistoryControls', '<PeriodSelect', '<InsightCard',
    ]) {
      assert.ok(src.includes(c), `${c} should be reused`)
    }
    assert.ok(!/<svg/.test(withoutDocComments(src)), 'no hand-rolled chart')
  })

  test('defaults to Production, like Growth and Collectives', () => {
    assert.match(read(PAGE), /useState<PopulationKey>\('production'\)/)
  })
})

describe('a count axis steps in whole things', () => {
  test('a small count range does not produce half-unit ticks', () => {
    // "0 / 0.5 / 1" on a chart of creators registered reads as half a
    // creator, which is a precision the data does not have.
    const d = niceDomain([0, 1, 1, 0], 4, { integer: true })
    for (const t of d.ticks) {
      assert.equal(t, Math.round(t), `tick ${t} is not a whole number`)
    }
  })

  test('the integer constraint never collapses the axis', () => {
    for (const values of [[0, 1], [1], [0, 2], [3, 7], [0, 0, 1]]) {
      const d = niceDomain(values, 4, { integer: true })
      assert.ok(d.max > d.min, `${values} collapsed`)
      assert.ok(d.ticks.length >= 2)
    }
  })

  test('money keeps its fine steps, because cents are already whole', () => {
    const d = niceDomain([0, 250, 500], 4)
    assert.ok(d.ticks.length >= 2)
    assert.ok(d.max >= 500)
  })

  test('a large count range is unaffected by the constraint', () => {
    const plain = niceDomain([0, 1200], 4)
    const integral = niceDomain([0, 1200], 4, { integer: true })
    assert.deepEqual(plain.ticks, integral.ticks)
  })

  test('the chart asks for integer steps only for counts', () => {
    const src = read('src/components/admin/insights/charts/TimeSeriesChart.tsx')
    assert.match(src, /integer: unit === 'count'/)
  })
})

describe('the cards describe the same population as the charts', () => {
  const PAGES = [
    'src/app/admin/insights/growth/page.tsx',
    'src/app/admin/insights/money/page.tsx',
    'src/app/admin/insights/collectives/page.tsx',
    'src/app/admin/insights/creators/page.tsx',
  ]

  test('every page passes its population to its metric cards', () => {
    // A page headed "Production" was showing production trends above
    // whole-platform figures, with nothing marking the difference.
    for (const path of PAGES) {
      const src = read(path)
      assert.ok(
        /useMetrics\([\s\S]{0,60}population/.test(src),
        `${path}: cards must honour the page filter`,
      )
    }
  })

  test('no page calls useMetrics without a population', () => {
    for (const path of PAGES) {
      const calls = [...read(path).matchAll(/useMetrics\(([\s\S]*?)\)/g)]
      assert.ok(calls.length > 0, path)
      for (const call of calls) {
        assert.ok(
          call[1].includes('population'),
          `${path}: ${call[0].replace(/\s+/g, ' ')} omits the population`,
        )
      }
    }
  })
})

describe('creator earnings say whose they are', () => {
  const PAGE = 'src/app/admin/insights/creators/page.tsx'

  test('the founder/independent split is shown, not just fetched', () => {
    const src = read(PAGE)
    assert.match(src, /by_operator_cents/)
    assert.match(src, /Independent creators/)
    assert.match(src, /Founder-operated Collectives/)
  })

  test('the split is read from the metric rather than computed here', () => {
    const src = read(PAGE)
    assert.ok(
      !/_cents'\)[^)]*\)?\s*[-+*/]\s*pick\(/.test(src),
      'the page must not do arithmetic between money metrics',
    )
  })

  test('period earnings and the current balance are separate bands', () => {
    const src = read(PAGE)
    const earned = src.indexOf('Earned and paid in')
    const owed = src.indexOf('Owed right now')
    assert.ok(earned > 0 && owed > earned, 'the two must not share a band')
    assert.match(src, /A balance at this moment, not a period figure/)
  })

  test('the outstanding balance names who is owed', () => {
    const src = read(PAGE)
    assert.match(src, /owed_to_external_creators_cents/)
    assert.match(src, /owed_to_founder_operated_collectives_cents/)
  })
})

describe('milestones reached and arrivals are not the same chart', () => {
  const PAGE = 'src/app/admin/insights/creators/page.tsx'

  test('the funnel is labelled cumulative', () => {
    const src = read(PAGE)
    assert.match(src, /Milestones reached, over time/)
    assert.match(src, /cumulative, not new activity/)
  })

  test('the arrivals chart says it is not the same thing', () => {
    const src = read(PAGE)
    assert.match(src, /New arrivals in each period/)
    assert.match(src, /Not the same thing as the chart/)
    assert.match(src, /rises and falls/)
  })

  test('the funnel base includes operators, not just the creator role', () => {
    // The founder holds an admin role and operates two Collectives;
    // a role-only base let the funnel widen instead of narrowing.
    const src = read(PAGE)
    const keys = /const HISTORY_KEYS = \[([\s\S]*?)\]/.exec(src)?.[1] ?? ''
    assert.ok(keys.includes('creator_accounts'), 'the base must be operators')
    assert.ok(
      !keys.includes('registered_creators'),
      'registered_creators counts the creator role alone',
    )
  })
})

describe('the Participation page keeps people and acts apart', () => {
  const PAGE = 'src/app/admin/insights/participation/page.tsx'

  test('it exists and leads with charts', () => {
    const src = read(PAGE)
    assert.ok(src.indexOf('<HistoryControls') < src.indexOf('<HistoryPanel'))
    assert.ok(src.indexOf('<HistoryPanel') < src.indexOf('<InsightCard'))
  })

  test('the distinct-people metrics are charted, not just the act counts', () => {
    const src = read(PAGE)
    for (const key of [
      'active_members', 'gathering_attendees',
      'pathway_participants', 'conversation_contributors',
    ]) {
      assert.ok(src.includes(key), `${key} should be on the page`)
    }
  })

  test('bookings and attendance are both charted', () => {
    const src = read(PAGE)
    assert.ok(src.includes('gathering_bookings'))
    assert.ok(src.includes('gathering_attendance'))
    assert.match(src, /never assumed from a booking/)
  })

  test('it says plainly that membership is not participation', () => {
    const src = read(PAGE)
    assert.match(src, /took part in the period/)
    assert.match(src, /whether they took part or not/)
  })

  test('it introduces no blended engagement score', () => {
    const src = read(PAGE)
    assert.ok(!/engagementScore|blendedScore|overallScore/i.test(src))
    assert.ok(
      !/participation_acts'\)[^)]*\)?\s*[-+*/]\s*pick\(/.test(src),
      'activity types must not be combined',
    )
  })

  test('Pathways are two charts, not one shared axis', () => {
    // Steps outnumber people several times over, so a shared axis
    // flattened the people series into the baseline — and a second
    // y-axis would be worse, because two scales on one frame can be
    // drawn to show any relationship you like.
    const src = read(PAGE)
    assert.match(src, /People progressing through Pathways/)
    assert.match(src, /Pathway steps completed/)
    const combined = /keys=\{\['pathway_steps_completed', 'pathway_participants'\]\}/
    assert.ok(!combined.test(src), 'the two must not share one chart')
    // And they stay under the same section, so the pairing is visible.
    const heading = src.indexOf('title="Pathways"')
    const people = src.indexOf('People progressing through Pathways')
    const steps = src.indexOf('Pathway steps completed')
    assert.ok(heading > 0, 'the Pathways section should still exist')
    assert.ok(heading < people && people < steps, 'in that order')
  })

  test('the participation rate is formatted from the registry unit', () => {
    // 0.75 of the membership was rendering as "0.75". The fix is a
    // declared unit, not a special case in the page.
    const src = read(PAGE)
    assert.ok(
      !/participation_rate[\s\S]{0,200}\*\s*100/.test(src),
      'the page must not convert a proportion itself',
    )
    assert.match(src, /share of members taking part/)
  })

  test('it explains why Pathway completion is absent rather than guessing', () => {
    const src = read(PAGE)
    assert.match(src, /completion/i)
    assert.match(src, /nothing in the application records a completion/)
    assert.match(src, /estimate presented as a measurement/)
  })

  test('the privacy boundary is stated on the Conversations section', () => {
    const src = read(PAGE)
    assert.match(src, /never reads what anybody wrote/)
  })

  test('the activity mix is read from the metric, not recomputed', () => {
    const src = read(PAGE)
    assert.match(src, /by_kind/)
    assert.match(src, /acts<\/strong>, not people/)
  })

  test('it defaults to Production and passes it to the cards', () => {
    const src = read(PAGE)
    assert.match(src, /useState<PopulationKey>\('production'\)/)
    const calls = [...src.matchAll(/useMetrics\(([\s\S]*?)\)/g)]
    assert.ok(calls.length > 0)
    for (const call of calls) {
      assert.ok(call[1].includes('population'), call[0].replace(/\s+/g, ' '))
    }
  })

  test('it reuses the shared components rather than drawing its own charts', () => {
    const src = read(PAGE)
    for (const c of [
      '<HistoryPanel', '<HistoryControls', '<PeriodSelect',
      '<CollectiveSelect', '<InsightCard',
    ]) {
      assert.ok(src.includes(c), `${c} should be reused`)
    }
    assert.ok(!/<svg/.test(withoutDocComments(src)), 'no hand-rolled chart')
  })

  test('the returning definition is spelled out, including what changes it', () => {
    const src = read(PAGE)
    assert.match(src, /immediately preceding period of the same length/)
    assert.match(src, /undefined over all time/)
  })
})

describe('retention cohorts leave unreached milestones blank', () => {
  const offset = (n: number, over: Partial<CohortOffset> = {}): CohortOffset => ({
    months_after: n, retained_in_collective: 5, retained_anywhere: 6,
    reached: true, ...over,
  })
  const row = (over: Partial<CohortRow> = {}): CohortRow => ({
    cohort: '2026-07', memberships_started: 10, people_joined: 8,
    offsets: [offset(1), offset(2)], ...over,
  })

  test('a reached milestone is a share of its own denominator', () => {
    const r = row()
    assert.equal(retentionRate(r, r.offsets[0], 'in_collective'), 0.5)
    assert.equal(retentionRate(r, r.offsets[0], 'anywhere'), 0.75)
  })

  test('the two bases use different denominators', () => {
    // A person who joined two Collectives in one month is two
    // memberships and one person; sharing a denominator would put a
    // figure above 100%.
    const r = row({ memberships_started: 10, people_joined: 5 })
    const o = offset(1, { retained_in_collective: 8, retained_anywhere: 5 })
    assert.equal(retentionRate(r, o, 'in_collective'), 0.8)
    assert.equal(retentionRate(r, o, 'anywhere'), 1)
  })

  test('an unreached milestone has no rate at all', () => {
    const o = offset(3, {
      reached: false, retained_in_collective: null, retained_anywhere: null,
    })
    assert.equal(retentionRate(row(), o, 'in_collective'), null)
    assert.equal(retentionRate(row(), o, 'anywhere'), null)
  })

  test('an unreached milestone renders blank, never zero per cent', () => {
    assert.equal(formatRetention(null), '—')
    assert.notEqual(formatRetention(null), '0%')
    assert.equal(formatRetention(0), '0%', 'a measured zero still shows')
  })

  test('a measured zero is distinguishable from an unreached one', () => {
    const measured = offset(1, { retained_in_collective: 0 })
    assert.equal(retentionRate(row(), measured, 'in_collective'), 0)
    assert.equal(formatRetention(0), '0%')
  })

  test('an empty cohort cannot produce a rate', () => {
    const r = row({ memberships_started: 0, people_joined: 0 })
    assert.equal(retentionRate(r, r.offsets[0], 'in_collective'), null)
  })

  test('columns cover every offset any cohort has reached', () => {
    const rows = [
      row({ cohort: '2026-07', offsets: [offset(1), offset(2), offset(3)] }),
      row({ cohort: '2026-09', offsets: [offset(1), offset(2, { reached: false })] }),
    ]
    assert.deepEqual(reachedOffsets(rows), [1, 2, 3])
  })

  test('an offset no cohort has reached gets no column', () => {
    const rows = [row({ offsets: [offset(1), offset(2, { reached: false })] })]
    assert.deepEqual(reachedOffsets(rows), [1])
  })

  test('cohort labels read as months', () => {
    assert.equal(cohortLabel('2026-09'), 'Sep 2026')
    assert.equal(cohortLabel('nonsense'), 'nonsense')
  })
})

describe('the Belonging page', () => {
  const PAGE = 'src/app/admin/insights/belonging/page.tsx'
  const TABLE = 'src/components/admin/insights/CohortTable.tsx'

  test('it says up front that it does not measure belonging', () => {
    const src = read(PAGE)
    assert.match(src, /Belonging is a feeling, and none of these figures measures it/)
    assert.ok(src.indexOf('<Caveat') < src.indexOf('<HistoryPanel'))
  })

  test('membership retention and participation retention are separate sections', () => {
    const src = read(PAGE)
    const membership = src.indexOf('Retention by joining month')
    const participation = src.indexOf('Returning to participate')
    assert.ok(membership > 0 && participation > membership)
  })

  test('leaving a Collective is distinguished from leaving entirely', () => {
    const src = read(PAGE)
    assert.match(src, /memberships_ended/)
    assert.match(src, /members_leaving_entirely/)
    assert.match(src, /Leaving one Collective while remaining in another is not counted/)
  })

  test('membership overlap is distinguished from cross-Collective participation', () => {
    const src = read(PAGE)
    assert.match(src, /multi_collective_participants/)
    assert.match(src, /members_in_three_plus_collectives/)
    assert.match(src, /an act, not a membership/)
  })

  test('the overlap comparison is descriptive, never causal', () => {
    // Flattened first: the sentence wraps across JSX lines, and a
    // scan of the raw file reads the wrap as an absence.
    const src = flatten(read(PAGE))
    assert.match(src, /A description, not an explanation/)
    assert.match(src, /cannot tell which way the arrow points/)
    assert.match(src, /as likely to be the cause of joining again as its result/)
  })

  test('rejoining discloses that it cannot be reconstructed', () => {
    const src = read(PAGE)
    assert.match(src, /cannot be reconstructed/)
    assert.match(src, /not the same as nobody having rejoined/)
  })

  test('undated departures are disclosed as a lower bound', () => {
    const src = read(PAGE)
    assert.match(src, /lower bound/)
    assert.ok(!/assume.{0,30}nobody left/i.test(src))
  })

  test('the cohort table is a real table, not a chart', () => {
    const src = read(TABLE)
    assert.match(src, /<table/)
    assert.match(src, /<caption/)
    assert.match(src, /scope="col"/)
    assert.match(src, /scope="row"/)
  })

  test('the cohort table offers both retention bases', () => {
    const src = read(TABLE)
    assert.match(src, /of the Collective they joined/)
    assert.match(src, /of Fresh Collective, anywhere/)
    assert.match(src, /aria-pressed=\{basis === key\}/)
  })

  test('a blank cohort cell is explained rather than left ambiguous', () => {
    const src = read(TABLE)
    assert.match(src, /not a\s*\n?\s*retention of zero/)
    assert.match(src, /has not been reached yet/)
  })

  test('it defaults to Production and passes it everywhere', () => {
    const src = read(PAGE)
    assert.match(src, /useState<PopulationKey>\('production'\)/)
    for (const call of src.matchAll(/useMetrics\(([\s\S]*?)\)/g)) {
      assert.ok(call[1].includes('population'), call[0].replace(/\s+/g, ' '))
    }
  })

  test('it reuses the shared components', () => {
    const src = read(PAGE)
    for (const c of [
      '<HistoryPanel', '<HistoryControls', '<PeriodSelect', '<InsightCard',
      '<CohortTable',
    ]) {
      assert.ok(src.includes(c), `${c} should be reused`)
    }
    assert.ok(!/<svg/.test(withoutDocComments(src)), 'no hand-rolled chart')
  })

  test('nothing judges somebody for participating less', () => {
    const src = withoutDocComments(read(PAGE))
    assert.ok(!/\b(disengaged|lapsed|at risk|inactive user|churned)\b/i.test(src))
  })
})

/**
 * The heading ladder.
 *
 * Six ranks share one page — the suite name, the page title, a section,
 * the chart leading that section, the charts supporting it, and a card
 * heading. Two of them drifted to the same size during the visual pass
 * and the page flattened: a section and the first chart inside it read
 * as peers, so nothing told the eye where a section began.
 *
 * Sizes are pinned rather than merely ordered because the failure is a
 * *tie*, not an inversion. Any future edit that gives two ranks the
 * same size is the bug this test exists to catch.
 */
describe('World Insights heading ladder', () => {
  const sizes = (src: string) =>
    [...withoutDocComments(src).matchAll(/text-\[([\d.]+)px\]/g)].map((m) =>
      Number(m[1]),
    )

  test('each rank is a step below the one above it', () => {
    const panel = withoutDocComments(
      read('src/components/admin/insights/HistoryPanel.tsx'),
    )
    const ladder = {
      page: Math.max(
        ...sizes(read('src/components/admin/insights/InsightsShell.tsx')),
      ),
      section: Math.max(
        ...sizes(read('src/components/admin/insights/InsightsSection.tsx')),
      ),
      leadPanel: Number(
        /prominent \? 'text-\[([\d.]+)px\]'/.exec(panel)?.[1] ?? NaN,
      ),
      panel: Number(
        /prominent \? 'text-\[[\d.]+px\]' : 'text-\[([\d.]+)px\]'/.exec(
          panel,
        )?.[1] ?? NaN,
      ),
    }
    const order = ['page', 'section', 'leadPanel', 'panel'] as const
    for (const rank of order) {
      assert.ok(Number.isFinite(ladder[rank]), `${rank} size not found`)
    }
    for (let i = 1; i < order.length; i += 1) {
      const above = order[i - 1]
      const here = order[i]
      assert.ok(
        ladder[here] < ladder[above],
        `${here} (${ladder[here]}px) must be smaller than ${above} ` +
          `(${ladder[above]}px) — equal sizes collapse the hierarchy`,
      )
    }
  })

  test('a titled panel inside a section sits at one size, not five', () => {
    // These drifted to 15px, 16px and 19px across six pages, which read
    // as five ranks where the design has one.
    const found = new Set<number>()
    for (const p of [
      'src/app/admin/insights/growth/page.tsx',
      'src/app/admin/insights/money/page.tsx',
      'src/app/admin/insights/collectives/page.tsx',
      'src/app/admin/insights/creators/page.tsx',
      'src/app/admin/insights/participation/page.tsx',
      'src/app/admin/insights/belonging/page.tsx',
      'src/components/admin/insights/StandingsTable.tsx',
    ]) {
      for (const m of withoutDocComments(read(p)).matchAll(
        /font-serif text-\[([\d.]+)px\]/g,
      )) {
        found.add(Number(m[1]))
      }
    }
    assert.deepEqual(
      [...found],
      [15.5],
      `panel headings should all be 15.5px, found ${[...found].join(', ')}`,
    )
  })
})

/**
 * Contrast, computed rather than judged.
 *
 * Two supporting ink steps shipped below AA because they were chosen
 * by eye — 4.4:1 and 3.3:1, the lighter one colouring an interactive
 * disclosure button. Both looked fine. Contrast is arithmetic, so it
 * is checked as arithmetic.
 *
 * Data marks are exempt from the text thresholds: a 2px line is not
 * text, every chart carries a legend and direct labels, and the
 * registry's table view restates each series. Gold sits at 2.08:1
 * against white and is legitimate for that reason — but only for
 * that reason, so it is pinned here as a mark and never used as ink.
 */
describe('World Insights contrast', () => {
  const WHITE = '#FFFFFF'

  const channel = (v: number) =>
    v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4

  const bytes = (hex: string) =>
    [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))

  /**
   * Flatten an rgba() over the surface it actually sits on.
   *
   * The backdrop is a parameter because getting it wrong makes the
   * check pass while measuring nothing: the navy card's ink is white
   * at a low alpha, and compositing that over an assumed white page
   * returns pure white and a triumphant 18:1.
   */
  const solid = (c: string, backdrop: string) => {
    const m = /rgba?\((\d+), *(\d+), *(\d+)(?:, *([\d.]+))?\)/.exec(c)
    if (!m) return c
    const a = m[4] === undefined ? 1 : Number(m[4])
    const base = bytes(backdrop)
    return `#${[1, 2, 3]
      .map((i) =>
        Math.round(Number(m[i]) * a + base[i - 1] * (1 - a))
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')}`
  }

  const luminance = (colour: string, backdrop: string) => {
    const [r, g, b] = bytes(solid(colour, backdrop)).map((v) =>
      channel(v / 255),
    )
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }

  /** ``fg`` is composited over ``bg``, which must itself be opaque. */
  const ratio = (fg: string, bg: string) => {
    const [hi, lo] = [luminance(fg, bg), luminance(bg, bg)].sort(
      (a, b) => b - a,
    )
    return (hi + 0.05) / (lo + 0.05)
  }

  test('every ink step clears AA for normal text on white', () => {
    for (const [name, colour] of Object.entries(INK)) {
      const r = ratio(colour, WHITE)
      assert.ok(
        r >= 4.5,
        `INK.${name} (${colour} → ${solid(colour, WHITE)}) is ` +
          `${r.toFixed(2)}:1 ` +
          `on white, below AA 4.5:1`,
      )
    }
  })

  test('every status colour is readable as text', () => {
    for (const [name, step] of Object.entries(STATUS)) {
      const r = ratio(step.fg, WHITE)
      assert.ok(r >= 4.5, `STATUS.${name}.fg is ${r.toFixed(2)}:1, below 4.5:1`)
    }
  })

  test('the readable form of each hue is readable', () => {
    for (const [name, step] of Object.entries(HUE_UI)) {
      const r = ratio(step.text, WHITE)
      assert.ok(r >= 4.5, `HUE_UI.${name}.text is ${r.toFixed(2)}:1`)
    }
  })

  test('the navy card is Fresh Collective\'s own inverse surface', () => {
    // Not a new navy, and not --fc-pathway-navy (a Pathway content
    // colour). #071824 is --fc-surface-inverse: every PageHero, the
    // top of the public footer, and four occurrences on the homepage.
    assert.equal(CARD.surface, '#071824')
    const tokens = readFileSync(
      join(ROOT, 'src/styles/fc-tokens.css'),
      'utf8',
    )
    assert.match(tokens, /--fc-surface-inverse:\s*#071824/i)
  })

  test('every colour on the navy card clears AA against it', () => {
    const navy = CARD.surface
    const checks: Array<[string, string]> = [
      ['ink', CARD.ink] as [string, string],
      ...Object.entries(CARD.status).map(
        ([k, v]) => [`status.${k}`, v] as [string, string],
      ),
      // The hues carry text on this surface too — the gold qualifier
      // note is drawn in CARD.hue.gold — so they are held to the
      // text threshold here rather than the 3:1 graphical one.
      ...Object.entries(CARD.hue).map(
        ([k, v]) => [`hue.${k}`, v] as [string, string],
      ),
      ['focus', CARD.focus],
    ]
    for (const [name, colour] of checks) {
      const r = ratio(colour, navy)
      assert.ok(
        r >= 4.5,
        `CARD.${name} (${colour}) is ${r.toFixed(2)}:1 on ${navy}, ` +
          `below AA 4.5:1`,
      )
    }
  })

  test('colours survive the lightest navy surface, not just the card', () => {
    // A tinted note is navy plus a 10% wash, so it is lighter than the
    // card and is the surface that actually binds. An earlier error
    // red cleared AA on the card at 4.61:1 and failed here at 3.92:1 —
    // the card alone is the easier test, and passing it proves little.
    for (const [accent, tint] of Object.entries(CARD.noteTint)) {
      const surface = solid(tint, CARD.surface)
      assert.ok(
        luminance(surface, surface) > luminance(CARD.surface, CARD.surface),
        `the ${accent} note should be lighter than the card`,
      )
      const checks = {
        ink: CARD.ink,
        ...CARD.status,
        ...CARD.hue,
      } as Record<string, string>
      for (const [name, colour] of Object.entries(checks)) {
        const r = ratio(colour, surface)
        assert.ok(
          r >= 4.5,
          `${name} (${colour}) is ${r.toFixed(2)}:1 on the ${accent} note ` +
            `(${surface}), below AA 4.5:1`,
        )
      }
    }
  })

  test('the dark palette is selected, not the light one flipped', () => {
    // The failure this guards against is reusing a light-surface
    // colour on navy because it is "the same hue". Two of them do not
    // survive the move: the deep status red falls to 2.79:1 and the
    // navy series mark to 2.84:1.
    assert.notEqual(CARD.status.error, STATUS.error.fg)
    assert.notEqual(CARD.status.warning, STATUS.warning.fg)
    for (const hue of Object.keys(CARD.hue)) {
      const onNavy = CARD.hue[hue as keyof typeof CARD.hue]
      assert.ok(
        ratio(onNavy, CARD.surface) >= 4.5,
        `${hue} must be restepped for navy if the light value fails there`,
      )
    }
  })

  test('dark cards carry pure white, never a dimmed white', () => {
    // The ladder of translucent whites that preceded this all cleared
    // AA and still read as grey. Rank is type now, not opacity, so a
    // reintroduced rgba() here is the regression to catch.
    assert.equal(CARD.ink, '#FFFFFF')
  })

  test('nothing on a dark card is italic', () => {
    // A whole supporting sentence in italic serif is harder to read
    // than the figure it supports. Page-level notes on the white
    // background keep theirs; these components are the dark ones.
    for (const f of [
      'src/components/admin/insights/InsightCard.tsx',
      'src/app/admin/insights/growth/page.tsx',
      'src/app/admin/insights/money/page.tsx',
      'src/app/admin/insights/creators/page.tsx',
    ]) {
      const src = withoutDocComments(read(f))
      assert.ok(
        !/fontStyle:\s*'italic'/.test(src),
        `${f} still sets an italic on a dark card`,
      )
    }
  })

  test('every emphasis surface carries white text accessibly', () => {
    for (const [kind, step] of Object.entries(EMPHASIS)) {
      for (const [which, bg] of [
        ['surface', step.surface],
        ['hover', step.hover],
      ] as const) {
        const r = ratio('#FFFFFF', bg)
        assert.ok(
          r >= 4.5,
          `EMPHASIS.${kind}.${which} (${bg}) gives white ${r.toFixed(2)}:1, ` +
            `below AA 4.5:1`,
        )
      }
    }
  })

  test('the status chip darkens its card, so white still clears AA', () => {
    // A translucent white chip is the obvious choice and is wrong: it
    // lightens the surface and took white below AA on obligation
    // (4.12:1) and warning (3.54:1).
    const src = read('src/components/admin/insights/InsightCard.tsx')
    const chip = /background: 'rgba\(0, 0, 0, ([\d.]+)\)'/.exec(src)
    assert.ok(chip, 'the emphasis chip should darken, not lighten')
    const alpha = Number(chip[1])
    for (const [kind, step] of Object.entries(EMPHASIS)) {
      const base = [1, 3, 5].map((i) =>
        parseInt(step.surface.slice(i, i + 2), 16),
      )
      const darkened = `#${base
        .map((v) =>
          Math.round(v * (1 - alpha))
            .toString(16)
            .padStart(2, '0'),
        )
        .join('')}`
      const r = ratio('#FFFFFF', darkened)
      assert.ok(r >= 4.5, `${kind} chip gives white ${r.toFixed(2)}:1`)
    }
  })

  test('watermelon itself is too light to host white text', () => {
    // The reason `obligation` is #A8402C and not the watermelon a
    // reader sees on the charts. Stated as a test so the "just use
    // the brand colour" edit fails rather than ships.
    assert.ok(ratio('#FFFFFF', HUE_MARK.watermelon) < 4.5)
    assert.equal(EMPHASIS.obligation.surface, HUE_UI.watermelon.text)
  })

  test('an obligation is not an overdue one, nor a failure', () => {
    // Money owed and not yet paid is the normal state of a payouts
    // ledger. If it shared a colour with a failure, the colour that
    // means failure would stop meaning anything.
    const surfaces = Object.values(EMPHASIS).map((e) => e.surface)
    assert.equal(new Set(surfaces).size, surfaces.length)
    const labels = Object.values(EMPHASIS).map((e) => e.label)
    assert.equal(new Set(labels).size, labels.length)
    assert.equal(EMPHASIS.obligation.label, 'Outstanding')
    assert.notEqual(EMPHASIS.obligation.surface, EMPHASIS.overdue.surface)
  })

  test('status never collides with an identity hue', () => {
    // Watermelon is an ordinary series colour and the error red is an
    // obligation. If they converge, one of the two stops meaning what
    // it says.
    for (const [sName, step] of Object.entries(STATUS)) {
      for (const [hName, hue] of Object.entries(HUE_MARK)) {
        assert.notEqual(
          step.fg.toLowerCase(),
          hue.toLowerCase(),
          `STATUS.${sName} and the ${hName} series are the same colour`,
        )
      }
    }
    // The same rule on navy, where watermelon and a red sit closer.
    for (const [sName, fg] of Object.entries(CARD.status)) {
      if (sName === 'healthy') continue // healthy is teal by design
      for (const [hName, hue] of Object.entries(CARD.hue)) {
        assert.notEqual(
          fg.toLowerCase(),
          hue.toLowerCase(),
          `CARD.status.${sName} and the ${hName} series are the same`,
        )
      }
    }
  })
})

/**
 * The World Builders dashboard.
 *
 * Three claims hold this page up, and each fails quietly rather than
 * loudly if it breaks: the Collective stays excluded from Production,
 * access is not presented as a decision anybody made, and nothing
 * implies a Pathway was finished.
 */
describe('World Builders dashboard', () => {
  const PAGE = 'src/app/admin/insights/world-builders/page.tsx'
  const src = () => withoutDocComments(read(PAGE))

  test('it is a tab of its own, not a section of Creators', () => {
    const shell = read('src/components/admin/insights/InsightsShell.tsx')
    assert.match(shell, /href: '\/admin\/insights\/world-builders'/)
    assert.doesNotThrow(() => read(PAGE))
  })

  test('it finds the Collective by rule, never by name', () => {
    // A slug can change and a name can be shared. The product locates
    // World Builders by `auto_grant_role` everywhere else and so does
    // this page, through the API's `learning_environment` flag.
    assert.match(src(), /learning_environment/)
    assert.ok(
      !/slug\s*===\s*['"]world-builders['"]/.test(src()),
      'the page must not match on a slug',
    )
    assert.ok(
      !/name\s*===\s*['"]World Builders['"]/.test(src()),
      'the page must not match on a name',
    )
  })

  test('it does not reclassify anything to make itself visible', () => {
    // The fix for "World Builders is invisible" must never be to make
    // it production — that would corrupt the other six dashboards.
    assert.ok(!/['"]production['"]/.test(src()))
    assert.match(src(), /internal operations|internal_operations/)
  })

  test('it presents no Joined stage', () => {
    // Membership is auto-granted, so a funnel step called "joined"
    // would describe a decision nobody made.
    assert.ok(
      /automatically/.test(src()),
      'the page must say access is automatic',
    )
    assert.ok(
      !/>\s*Joined\s*</.test(src()),
      'there must be no Joined stage',
    )
  })

  test('it never claims a Pathway was completed', () => {
    const text = src()
    // Steps are counted and said so; a finished Pathway is not.
    assert.match(text, /pathway_steps_completed/)
    assert.ok(
      !/\bcompleted a Pathway\b/.test(text),
      'nothing may claim a finished Pathway',
    )
    assert.match(text, /No completion event is emitted/)
  })

  test('it names what it cannot measure rather than leaving a gap', () => {
    for (const absent of [
      'Pathway completion',
      'Resource and Offering use',
      'First Pathway or Gathering published',
    ]) {
      assert.ok(src().includes(absent), `${absent} should be named as absent`)
    }
  })

  test('creator development is described, never explained', () => {
    assert.match(src(), /not evidence that World Builders caused it/)
    assert.ok(
      !/because of World Builders|thanks to World Builders/i.test(src()),
      'no causal claim',
    )
  })

  test('it reuses the shared components and adds no arithmetic', () => {
    for (const c of ['<HistoryPanel', '<InsightCard', '<CardNote', '<PeriodSelect']) {
      assert.ok(src().includes(c), `${c} should be reused`)
    }
    assert.ok(!/<svg/.test(src()), 'no hand-rolled chart')
  })
})

/**
 * Wide content scrolls inside its own container.
 *
 * The application ``body`` is a flex container, so every child of it
 * takes ``min-width: auto`` and refuses to shrink below its content's
 * min-content width. One table with a ``min-w-[420px]`` inside a card
 * inside the shell therefore widened the entire page at 390px and
 * made the body scroll sideways — the exact thing the design rules
 * forbid, caused by a class nobody would think to look at.
 */
describe('the insights shell can shrink', () => {
  test('the shell root allows itself to be narrowed', () => {
    const shell = read('src/components/admin/insights/InsightsShell.tsx')
    assert.match(
      shell,
      /className="min-h-full min-w-0"/,
      'without min-w-0 the shell cannot shrink inside the flex body, and ' +
        'any wide child widens the whole page',
    )
  })

  test('a table that needs more room scrolls in its own container', () => {
    const page = read('src/app/admin/insights/world-builders/page.tsx')
    const table = /<table[^>]*min-w-\[/.test(page)
    if (!table) return
    assert.match(
      page,
      /overflow-x-auto/,
      'a min-width table must sit inside a scroll container',
    )
  })
})

/**
 * The graduated card surfaces.
 *
 * Six rows of one navy read as a slab, so the figures band now walks
 * navy → midnight → ocean → rich teal. Three things can quietly break
 * that: a step too bright for white text, a progression that stops
 * being a progression, and colour bound to the physical row instead
 * of the logical group.
 */
describe('the metric-card ramp', () => {
  const WHITE = '#FFFFFF'

  const rgb = (hex: string) =>
    [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))

  const chan = (v: number) =>
    v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4

  const lum = (hex: string) => {
    const [r, g, b] = rgb(hex).map((v) => chan(v / 255))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }

  const contrast = (a: string, b: string) => {
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
    return (hi + 0.05) / (lo + 0.05)
  }

  /** A wash composited over a surface, as CardNote draws it. */
  const tinted = (tint: string, surface: string) => {
    const m = /rgba\((\d+), *(\d+), *(\d+), *([\d.]+)\)/.exec(tint)!
    const base = rgb(surface)
    return `#${[1, 2, 3]
      .map((i) =>
        Math.round(Number(m[i]) * Number(m[4]) + base[i - 1] * (1 - Number(m[4])))
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')}`
  }

  test('it starts on the platform\'s own inverse surface', () => {
    assert.equal(CARD_SURFACES.navy.surface, '#071824')
    const tokens = readFileSync(join(ROOT, 'src/styles/fc-tokens.css'), 'utf8')
    assert.match(tokens, /--fc-surface-inverse:\s*#071824/i)
  })

  test('every step carries pure white text accessibly', () => {
    for (const step of SURFACE_ORDER) {
      const r = contrast(WHITE, CARD_SURFACES[step].surface)
      assert.ok(
        r >= 4.5,
        `${step} (${CARD_SURFACES[step].surface}) gives white ` +
          `${r.toFixed(2)}:1, below AA 4.5:1`,
      )
    }
  })

  test('it actually progresses, rather than just differing', () => {
    // Each step lighter than the last. A ramp that wandered would
    // still pass a contrast check and would not read as a direction.
    const lums = SURFACE_ORDER.map((s) => lum(CARD_SURFACES[s].surface))
    for (let i = 1; i < lums.length; i += 1) {
      assert.ok(
        lums[i] > lums[i - 1],
        `${SURFACE_ORDER[i]} must be lighter than ${SURFACE_ORDER[i - 1]}`,
      )
    }
  })

  test('an explanatory note stays legible on every step', () => {
    // The tint composites over the group's surface, so the brightest
    // step is the one that binds — and a note on rich teal is the
    // lightest surface white text ever sits on.
    for (const step of SURFACE_ORDER) {
      for (const accent of ['teal', 'gold'] as const) {
        const surface = tinted(
          CARD.noteTint[accent],
          CARD_SURFACES[step].surface,
        )
        const r = contrast(WHITE, surface)
        assert.ok(
          r >= 4.5,
          `a ${accent} note on ${step} (${surface}) gives white ` +
            `${r.toFixed(2)}:1`,
        )
      }
    }
  })

  test('the focus ring survives the whole ramp', () => {
    // The accent teal reads 7.65:1 on navy and 2.25:1 on rich teal,
    // which is why the ring is white. A focus indicator is a non-text
    // graphic, so 3:1 is the bar.
    for (const step of SURFACE_ORDER) {
      const r = contrast(CARD.focus, CARD_SURFACES[step].surface)
      assert.ok(r >= 3, `focus ring on ${step} is ${r.toFixed(2)}:1`)
    }
  })

  test('the colour belongs to the group, not to the card', () => {
    // Cards read the surface from context so a group that is one row
    // on a desktop and four rows on a phone keeps one colour. A page
    // passing a surface to an individual card would break that at a
    // breakpoint, invisibly.
    for (const name of [
      'growth', 'money', 'collectives', 'creators',
      'participation', 'belonging', 'world-builders',
    ]) {
      const src = withoutDocComments(
        read(`src/app/admin/insights/${name}/page.tsx`),
      )
      assert.ok(
        !/<InsightCard[^>]*\bsurface=/s.test(src),
        `${name} assigns a surface to a card rather than to its group`,
      )
      if (src.includes('<CardGroup')) {
        assert.match(
          src,
          /surface=\{surfaceForGroup\(/,
          `${name} should take its surfaces from the shared ramp`,
        )
      }
    }
  })

  test('groups step down the ramp in order, and clamp', () => {
    assert.equal(surfaceForGroup(0), 'navy')
    assert.equal(surfaceForGroup(1), 'midnight')
    assert.equal(surfaceForGroup(2), 'ocean')
    assert.equal(surfaceForGroup(3), 'rich')
    // A page longer than the ramp repeats the last step rather than
    // wrapping back to navy, which would read as a new beginning.
    assert.equal(surfaceForGroup(4), 'rich')
    assert.equal(surfaceForGroup(9), 'rich')
  })

  test('emphasis still interrupts the ramp, and stays semantic', () => {
    // An emphasis card is allowed to break the progression — that is
    // the point of it — but only for the four declared meanings.
    const surfaces = SURFACE_ORDER.map((s) => CARD_SURFACES[s].surface)
    for (const [kind, step] of Object.entries(EMPHASIS)) {
      assert.ok(
        !surfaces.includes(step.surface),
        `EMPHASIS.${kind} must not reuse a ramp surface`,
      )
    }
    assert.equal(EMPHASIS.obligation.surface, '#A8402C')
    assert.notEqual(EMPHASIS.obligation.surface, EMPHASIS.overdue.surface)
    assert.notEqual(EMPHASIS.warning.surface, EMPHASIS.error.surface)
  })
})

/**
 * Emphasis cards sit on their own row.
 *
 * A watermelon card beside a rich teal one makes both harder to read
 * — two saturated surfaces at the same size compete, and the
 * emphasis stops reading as emphasis.
 */
describe('the emphasis row', () => {
  const src = () =>
    withoutDocComments(read('src/components/admin/insights/InsightsSection.tsx'))

  test('a group separates emphasised cards from ordinary ones', () => {
    assert.match(src(), /const standard = kids\.filter/)
    assert.match(src(), /const emphasised = kids\.filter/)
  })

  test('both rows share one column track, so they stay aligned', () => {
    // The emphasis card keeps its normal metric-card width rather than
    // stretching, which is what keeps it lined up with the row above.
    const grid = /const GRID = '([^']+)'/.exec(src())
    assert.ok(grid, 'the column track should be declared once')
    assert.match(grid[1], /sm:grid-cols-2/)
    assert.match(grid[1], /lg:grid-cols-4/)
    // Used for both rows, never redefined for one of them.
    assert.equal(src().match(/grid gap-3 sm:grid-cols-2/g)?.length, 1)
    assert.ok(
      !/col-span-full|w-full/.test(src()),
      'an emphasis card must not stretch across the row',
    )
  })

  test('no emphasis card means no extra row and no extra gap', () => {
    // Guarded on length, and the top margin only applies when there is
    // actually a row above to separate from.
    assert.match(src(), /emphasised\.length > 0 && \(/)
    assert.match(src(), /standard\.length > 0 \? ' mt-3' : ''/)
  })

  test('the split reads the card\'s own prop, not a page declaration', () => {
    // `emphasis` is conditional — outstanding payouts are only an
    // obligation while something is owed — so a page declaring the
    // layout would have to repeat that condition and the two would
    // drift apart.
    assert.match(src(), /function isEmphasised/)
    assert.match(src(), /isValidElement\(child\)/)
    assert.match(src(), /emphasis\?: unknown/)
  })

  test('every emphasis card on every page sits inside a group', () => {
    // The rule lives in CardGroup, so a card placed outside one would
    // silently opt out of it.
    for (const name of [
      'growth', 'money', 'collectives', 'creators',
      'participation', 'belonging', 'world-builders',
    ]) {
      const page = read(`src/app/admin/insights/${name}/page.tsx`)
      if (!/\bemphasis=/.test(withoutDocComments(page))) continue
      assert.match(
        page,
        /<CardGroup/,
        `${name} uses emphasis outside a CardGroup, which cannot apply ` +
          `the emphasis-row rule`,
      )
    }
  })
})
