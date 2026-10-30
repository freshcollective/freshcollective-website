import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  AVAILABILITY_PROSE,
  DATE_BASIS_PROSE,
  QUALITY_LABEL,
  axisLabelSpace,
  directLabelSpace,
  estimateTextWidth,
  historyQuality,
  pointQuality,
  populationNotes,
  tooltipLeft,
  xLabelCapacity,
  type HistoryPoint,
  type HistorySeries,
  CHART_HUES,
  HUE_STROKE,
  compactCount,
  compactMoney,
  dashRuns,
  describeGap,
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
  test('is the four World Management accents, in a fixed order', () => {
    assert.deepEqual([...CHART_HUES], ['teal', 'navy', 'gold', 'coral'])
  })

  test('carries the exact hexes that passed the palette validator', () => {
    // Re-stepping any of these invalidates the colour-vision
    // separation that was measured, so the values are pinned.
    assert.deepEqual(HUE_STROKE, {
      teal: '#22a598',
      navy: '#4c78d4',
      gold: '#d4b048',
      coral: '#d66057',
    })
  })

  test('every hue has a stroke, so a series can never fall back to none', () => {
    for (const hue of CHART_HUES) {
      assert.match(HUE_STROKE[hue], /^#[0-9a-f]{6}$/)
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
            ticks[i] - ticks[i - 1] >= stride / 2,
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
    const a = sound({ points: [point({ available: false, value: null })] })
    const b = sound({ key: 'b', points: [point()] })
    assert.ok(historyQuality([a, b]).some((q) => q.kind === 'unavailable'))
  })

  test('every kind has a label a reader can read', () => {
    for (const kind of [
      'observed', 'reconstructed', 'limited', 'incomplete', 'unavailable',
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
