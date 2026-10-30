import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  type MetricDefinition,
  type MetricValue,
  type ReportingHealth,
  type ReportingJobRun,
  PERIOD_OPTIONS,
  comparisonSentence,
  describeHealth,
  formatRate,
  formatValue,
  humaniseClass,
  isComparable,
  isMoney,
  outstandingBreakdown,
  qualifierNote,
} from './insights.ts'

/**
 * World Insights presentation rules.
 *
 * None of these assert a business figure — the metric registry owns
 * those and the backend suite tests them. What is tested here is the
 * part that could quietly mislead a reader: which state the data-health
 * indicator reports when several are true at once, whether a comparison
 * sentence is written when a percentage change would be undefined, and
 * that the pages themselves do no arithmetic of their own.
 */

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const read = (p: string) => readFileSync(join(ROOT, p), 'utf8')

/**
 * Drop JSDoc blocks before scanning page source for wording.
 *
 * The pages carry long comments explaining the very distinctions the
 * wording checks enforce, so a scan over the raw file reads the
 * explanation as a violation. Only `/** ... *\/` blocks are removed;
 * nothing here needs to survive a `/*` inside a string literal.
 */
const withoutDocComments = (src: string) => src.replace(/\/\*\*[\s\S]*?\*\//g, '')

/** Collapse wrapped JSX prose so a sentence can be read as a sentence. */
const flatten = (src: string) => src.replace(/\s+/g, ' ')

function definition(over: Partial<MetricDefinition> = {}): MetricDefinition {
  return {
    key: 'memberships_started',
    display_name: 'Memberships started',
    definition: 'Memberships that began in the period.',
    source_of_truth: 'space_members',
    grain: 'period',
    aggregation: 'additive',
    unit: 'count',
    date_basis: 'membership_joined',
    access: 'platform_only',
    availability: 'full',
    limitations: null,
    dimensions: [],
    personal_data: false,
    ...over,
  }
}

function metric(over: Partial<MetricValue> = {}): MetricValue {
  return {
    key: over.definition?.key ?? over.key ?? 'memberships_started',
    value: 0,
    available: true,
    unavailable_reason: null,
    qualifiers: {},
    definition: definition(),
    ...over,
  }
}

function run(over: Partial<ReportingJobRun> = {}): ReportingJobRun {
  return {
    job_name: 'reporting_nightly',
    status: 'succeeded',
    started_at: '2026-10-27T16:00:00',
    finished_at: '2026-10-27T16:00:20',
    reporting_date_from: '2026-10-24',
    reporting_date_to: '2026-10-26',
    days_processed: 3,
    rows_written: 60,
    error: null,
    ...over,
  }
}

function health(over: Partial<ReportingHealth> = {}): ReportingHealth {
  return {
    recording_enabled: true,
    activation_floor: '2026-09-20T00:00:00',
    events_total: 120,
    latest_event_at: '2026-10-27T02:14:00',
    event_counts_by_type: {},
    ok: true,
    total_missing: 0,
    checks: [],
    aggregates: {
      oldest_latest_reporting_date: '2026-10-26',
      newest_latest_reporting_date: '2026-10-26',
      metrics_stored: 20,
      rows_total: 400,
      per_metric: {},
    },
    last_run: run(),
    last_successful_run: run(),
    incomplete_runs: [],
    note: null,
    ...over,
  }
}

describe('the data-health indicator reports the awkward state first', () => {
  test('a healthy platform says so plainly', () => {
    assert.deepEqual(describeHealth(health(), false), {
      hue: 'teal',
      label: 'Data looks healthy',
    })
  })

  test('recording switched off outranks every other check', () => {
    // With no events arriving, the other checks are reading a stopped
    // clock — so this must win even when they all look fine.
    const state = describeHealth(health({ recording_enabled: false }), false)
    assert.equal(state.hue, 'coral')
    assert.equal(state.label, 'History recording is off')
  })

  test('a run that never finished outranks a successful last run', () => {
    const state = describeHealth(
      health({ incomplete_runs: [run({ status: 'running', finished_at: null })] }),
      false,
    )
    assert.equal(state.hue, 'coral')
  })

  test('a failed rebuild is reported even when nothing is missing', () => {
    const state = describeHealth(
      health({ last_run: run({ status: 'failed', error: 'boom' }) }),
      false,
    )
    assert.equal(state.hue, 'coral')
    assert.equal(state.label, 'Last reporting run failed')
  })

  test('unexplained gaps are amber, not red', () => {
    const state = describeHealth(health({ total_missing: 3 }), false)
    assert.equal(state.hue, 'gold')
    assert.equal(state.label, '3 to look at')
  })

  test('no trends built yet is a fact, not a fault', () => {
    // The nightly job may simply not have run. Live figures never depend
    // on it, so reporting this as a failure would teach somebody to
    // ignore the indicator.
    const state = describeHealth(
      health({
        last_run: null,
        last_successful_run: null,
        aggregates: { ...health().aggregates, rows_total: 0, metrics_stored: 0 },
      }),
      false,
    )
    assert.equal(state.hue, 'navy')
    assert.equal(state.label, 'Daily trends not built yet')
  })

  test('a quiet platform with no events at all is still healthy', () => {
    const state = describeHealth(
      health({ events_total: 0, latest_event_at: null }),
      false,
    )
    assert.equal(state.hue, 'teal')
  })

  test('an unreachable health endpoint never claims health either way', () => {
    assert.equal(describeHealth(null, true).hue, 'gold')
    assert.equal(describeHealth(null, false).hue, 'navy')
  })
})

describe('a figure is formatted as whatever it actually is', () => {
  test('money is formatted as currency, by its declared unit', () => {
    assert.equal(
      formatValue(
        metric({
          key: 'platform_fee_revenue_cents',
          value: 123456,
          definition: definition({
            key: 'platform_fee_revenue_cents',
            unit: 'money_cents',
          }),
        }),
      ),
      '$1,235',
    )
  })

  test('a definition with no unit still formats money as money', () => {
    // fc-web and fc-api deploy independently and in no guaranteed order,
    // so the browser can hold a definition from before the unit existed.
    // A money total rendered as a bare integer is a hundredfold error,
    // not a cosmetic one, so the key convention remains the fallback.
    const noUnit = definition({ key: 'platform_fee_revenue_cents' })
    delete (noUnit as { unit?: unknown }).unit
    assert.equal(
      formatValue(
        metric({ key: 'platform_fee_revenue_cents', value: 123456, definition: noUnit }),
      ),
      '$1,235',
    )
    assert.ok(isMoney('platform_fee_revenue_cents'))
    assert.ok(!isMoney('unique_members'))
  })

  test('a rate reads as a decimal, not a percentage', () => {
    // The defect this replaces: `memberships_per_member` aggregates as a
    // ratio, this module read "ratio" as "percentage", and 1.83
    // memberships per person was shown as 183%. A rate is not a part of
    // anything, so it has no percentage form.
    const m = metric({
      key: 'memberships_per_member',
      value: 1.83,
      definition: definition({
        key: 'memberships_per_member',
        aggregation: 'ratio',
        unit: 'rate',
        grain: 'snapshot',
      }),
    })
    assert.equal(formatValue(m), '1.83')
    assert.ok(!formatValue(m).includes('%'))
  })

  test('a whole-number rate drops its empty decimals', () => {
    assert.equal(formatRate(2), '2')
    assert.equal(formatRate(1.5), '1.50')
  })

  test('a proportion still reads as a percentage', () => {
    const m = metric({
      key: 'member_retention',
      value: 0.126,
      definition: definition({
        key: 'member_retention',
        aggregation: 'ratio',
        unit: 'proportion',
      }),
    })
    assert.equal(formatValue(m), '13%')
  })

  test('a small proportion keeps a decimal rather than rounding away', () => {
    const m = metric({
      key: 'member_retention',
      value: 0.042,
      definition: definition({
        key: 'member_retention',
        aggregation: 'ratio',
        unit: 'proportion',
      }),
    })
    assert.equal(formatValue(m), '4.2%')
  })

  test('the unit decides, not the aggregation', () => {
    // Two metrics with identical aggregation and different units must
    // format differently — otherwise the registry's declaration is
    // decorative and the next rate gets the same bug.
    const shared = { aggregation: 'ratio' as const, value: 0.5 }
    const asRate = metric({
      ...shared,
      definition: definition({ aggregation: 'ratio', unit: 'rate' }),
    })
    const asProportion = metric({
      ...shared,
      definition: definition({ aggregation: 'ratio', unit: 'proportion' }),
    })
    assert.notEqual(formatValue(asRate), formatValue(asProportion))
  })

  test('an absent figure is a dash, never a zero', () => {
    assert.equal(formatValue(metric({ value: null, available: false })), '—')
  })
})

describe('comparisons are only drawn where they mean something', () => {
  test('a snapshot is never compared across periods', () => {
    // Two snapshots each describe a moment, so subtracting one from the
    // other answers no question anybody asked.
    assert.ok(!isComparable(definition({ grain: 'snapshot' })))
    assert.ok(isComparable(definition({ grain: 'period' })))
  })

  test('a plain sentence, not an arrow and a figure', () => {
    assert.equal(
      comparisonSentence(
        metric({ value: 12 }),
        metric({ value: 8 }),
        'Last month',
      ),
      '4 more than last month (50%).',
    )
  })

  test('no change is said rather than shown as 0%', () => {
    assert.equal(
      comparisonSentence(metric({ value: 8 }), metric({ value: 8 }), 'Last month'),
      'Unchanged from last month.',
    )
  })

  test('growth from zero avoids an undefined percentage', () => {
    const sentence = comparisonSentence(
      metric({ value: 5 }),
      metric({ value: 0 }),
      'Last month',
    )
    assert.equal(sentence, '5 more than last month, which was none.')
    assert.ok(!sentence?.includes('Infinity'))
    assert.ok(!sentence?.includes('%'))
  })

  test('nothing is said when there is nothing to compare against', () => {
    assert.equal(comparisonSentence(metric({ value: 5 }), null, 'Last month'), null)
    assert.equal(
      comparisonSentence(metric({ value: 5 }), metric({ value: null }), 'Last month'),
      null,
    )
    assert.equal(comparisonSentence(metric({ value: 5 }), metric({ value: 1 }), null), null)
  })
})

describe('caveats come from the result, not from a hand-written caption', () => {
  test('silence when there is nothing to caveat', () => {
    assert.equal(qualifierNote(metric()), null)
  })

  test('a note mentioning approximation with no approximated rows stays silent', () => {
    // The backend returns the note describing its method whether or not
    // any row needed it. Repeating it over a clean period would be a
    // warning about nothing.
    const m = metric({
      qualifiers: { approximation_note: 'Older rows use created_at.', approximated_rows: 0 },
    })
    assert.equal(qualifierNote(m), null)
  })

  test('approximated settlement dates are stated with their count', () => {
    const m = metric({
      qualifiers: { approximation_note: 'Older rows use created_at.', approximated_rows: 4 },
    })
    assert.match(qualifierNote(m) ?? '', /^4 older payments are dated by when/)
  })

  test('an unreported Stripe fee makes the figure a lower bound, and says so', () => {
    const m = metric({
      key: 'processing_costs_cents',
      qualifiers: { fee_note: 'Fees arrive with the balance transaction.', rows_without_a_known_fee: 1 },
    })
    assert.match(qualifierNote(m) ?? '', /lower bound/)
    assert.match(qualifierNote(m) ?? '', /1 payment,? /)
  })

  test('a reconstructed figure admits what it cannot see', () => {
    const m = metric({
      qualifiers: { provenance: 'reconstructed', caveat: 'Rebuilt from current rows.' },
    })
    assert.match(qualifierNote(m) ?? '', /before we began recording history/)
  })
})

describe('the pages present figures rather than deriving them', () => {
  const PAGES = [
    'src/app/admin/insights/growth/page.tsx',
    'src/app/admin/insights/money/page.tsx',
  ]

  test('every page reads its figures through pick(), not by indexing the array', () => {
    for (const path of PAGES) {
      const source = read(path)
      assert.ok(source.includes('pick(data,'), `${path} should read metrics by key`)
      assert.ok(
        !/\.metrics\[\d+\]/.test(source),
        `${path} must not read metrics by position`,
      )
    }
  })

  test('no page recomputes a money total from other money totals', () => {
    // Contribution, earnings and fees are all registry metrics. A page
    // that subtracted one from another would be a second definition of
    // the same figure, which is the drift the registry exists to end.
    for (const path of PAGES) {
      const source = read(path)
      assert.ok(
        !/_cents'\)[^)]*\)?\s*[-+*/]\s*pick\(/.test(source),
        `${path} must not do arithmetic between money metrics`,
      )
    }
  })

  test('contribution is never called profit', () => {
    // Contribution is the figure most likely to be mistaken for profit,
    // and the mistake would flatter the business. The word is allowed —
    // the page says plainly that this is *not* profit — so what this
    // checks is that every mention is a denial.
    //
    // Doc comments are dropped first (a blunt scan would read the
    // comment explaining this rule as a breach of it) and the remainder
    // is flattened to one line, because the denial and the word it
    // denies are often split across a wrapped JSX paragraph.
    const source = flatten(
      withoutDocComments(read('src/app/admin/insights/money/page.tsx')),
    )
    const mentions = [...source.matchAll(/profit/gi)]
    assert.ok(mentions.length > 0, 'the page should state that this is not profit')
    for (const m of mentions) {
      const lead = source.slice(Math.max(0, m.index - 40), m.index)
      assert.match(
        lead,
        /\bnot\b|\bNot$/,
        `"profit" must only appear in a denial, near: ${source
          .slice(Math.max(0, m.index - 60), m.index + 20)
          .trim()}`,
      )
    }
  })

  test('both pages share one period control, so a period means one thing', () => {
    for (const path of PAGES) {
      assert.ok(read(path).includes('<PeriodSelect'), `${path} should use PeriodSelect`)
    }
  })

  test('every tab in the shell has a page behind it', () => {
    const shell = read('src/components/admin/insights/InsightsShell.tsx')
    const hrefs = [...shell.matchAll(/href: '\/admin\/insights\/([a-z-]+)'/g)].map(
      (m) => m[1],
    )
    assert.equal(hrefs.length, 6)
    for (const slug of hrefs) {
      assert.doesNotThrow(
        () => read(`src/app/admin/insights/${slug}/page.tsx`),
        `/admin/insights/${slug} is a tab with no page`,
      )
    }
  })

  test('data health is reachable from the header, not only a footer link', () => {
    const shell = read('src/components/admin/insights/InsightsShell.tsx')
    assert.ok(shell.includes('<DataHealthIndicator />'))
    assert.ok(shell.includes("href=\"/admin/insights/data-health\""))
    // It sits outside the six tabs by design.
    assert.ok(!shell.includes("href: '/admin/insights/data-health'"))
  })
})

describe('who an outstanding balance is owed to', () => {
  const split = (q: Record<string, unknown>) =>
    outstandingBreakdown(
      metric({ key: 'outstanding_payouts_cents', value: 156000, qualifiers: q }),
    )

  test('the two splits are read off the result, not computed here', () => {
    const b = split({
      owed_to_external_creators_cents: 0,
      owed_to_founder_operated_collectives_cents: 156000,
      by_reporting_class_cents: {
        production: 155800,
        demonstration: 200,
        internal_operations: 0,
        unclassified: 0,
      },
    })
    assert.equal(b?.externalCents, 0)
    assert.equal(b?.founderCents, 156000)
    assert.deepEqual(b?.byClass, { production: 155800, demonstration: 200 })
  })

  test('zero classes are dropped so a line of zeroes is never shown', () => {
    const b = split({
      owed_to_external_creators_cents: 100,
      owed_to_founder_operated_collectives_cents: 0,
      by_reporting_class_cents: { production: 0, unclassified: 100 },
    })
    assert.deepEqual(b?.byClass, { unclassified: 100 })
  })

  test('missing qualifiers give nothing rather than zeroes', () => {
    // Asserting "nothing is owed to anybody" from an absent field would
    // be the most misleading possible reading of this particular figure.
    assert.equal(split({}), null)
    assert.equal(outstandingBreakdown(null), null)
  })

  test('a partial qualifier set is rejected rather than half-read', () => {
    assert.equal(split({ owed_to_external_creators_cents: 100 }), null)
  })

  test('class names are written for a person', () => {
    assert.equal(humaniseClass('internal_operations'), 'Internal operations')
    assert.equal(humaniseClass('demonstration'), 'Demonstration')
  })
})

describe('the Money page distinguishes whose obligation it is', () => {
  const MONEY = read('src/app/admin/insights/money/page.tsx')

  test('the ownership split is shown, not just fetched', () => {
    assert.ok(MONEY.includes('<WhoIsOwedNote'))
    assert.ok(MONEY.includes('outstandingBreakdown('))
  })

  test('founder-operated money is never labelled a creator obligation', () => {
    const flat = flatten(withoutDocComments(MONEY))
    // The two amounts must carry different labels; one standing in for
    // both is the misreport this whole change exists to end.
    assert.ok(flat.includes('Independent creators'))
    assert.ok(flat.includes('Collectives you operate'))
  })

  test('the page says a bank payout does not clear a creator payout', () => {
    const flat = flatten(withoutDocComments(MONEY))
    assert.match(flat, /bank account is not a creator\s*payout/)
  })

  test('nothing on the page claims founder earnings are settled', () => {
    const flat = flatten(withoutDocComments(MONEY))
    for (const m of flat.matchAll(/settled/gi)) {
      const lead = flat.slice(Math.max(0, m.index - 60), m.index)
      assert.match(
        lead,
        /\bnot\b/,
        `"settled" must only appear in a denial, near: ${flat
          .slice(Math.max(0, m.index - 80), m.index + 20)
          .trim()}`,
      )
    }
  })
})

describe('the period choices', () => {
  test('offer the Australian financial year, which the backend resolves', () => {
    const keys = PERIOD_OPTIONS.map(([k]) => k)
    assert.deepEqual(keys, ['this_month', 'last_month', 'this_fy', 'all_time'])
  })
})
