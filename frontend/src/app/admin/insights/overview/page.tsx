'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { HistoryControls } from '@/components/admin/insights/HistoryControls'
import { HistoryPanel } from '@/components/admin/insights/HistoryPanel'
import { InsightsShell } from '@/components/admin/insights/InsightsShell'
import { useHistory } from '@/components/admin/insights/useHistory'
import { useMetrics } from '@/components/admin/insights/useMetrics'
import {
  type MetricResult,
  type MetricValue,
  type ReportingHealth,
  compactComparison,
  describeHealth,
  fetchHealth,
  formatCount,
  formatMoney,
  formatValue,
  outstandingBreakdown,
  pick,
  pickPrevious,
} from '@/lib/insights'
import {
  type Creator,
  type Grouping,
  type HistoryRangeKey,
  fetchCreators,
  stageCounts,
} from '@/lib/insights-history'
import {
  EMPHASIS,
  HUE_MARK,
  HUE_UI,
  INK as FC_INK,
  type InsightHue,
  STATUS,
  SURFACE,
  toneStyle,
} from '@/lib/insights-palette'

/**
 * World Insights Overview — a chart-led management dashboard.
 *
 * Deliberately unlike the seven dashboards behind it. Those are
 * reference documents: a band of figures, an explanation beside every
 * one, read when somebody has a question. This is the page somebody
 * opens with no question yet, so it is mostly pictures — a tight grid
 * of charts with four compact figures above them, rather than the
 * graduated bands of coloured cards the detailed pages use. Colour
 * lives in the plots here; the panels are white.
 *
 * One control, two vocabularies
 * -----------------------------
 * A single range selector drives everything, which needed ``/query``
 * to accept the rolling ranges ``/history`` already took. Mapping
 * between them in the client was the alternative and would have
 * mislabelled every figure: "last 3 months" is not "this month".
 *
 * Nothing is recomputed here. Every number is a registry metric
 * rendered as it arrived, and the creator funnel reuses the Creators
 * dashboard's own ``stageCounts`` rather than counting stages again.
 */

/** Production: people, Collectives, participation. */
const HEADLINE = ['unique_members', 'active_collectives', 'creator_accounts']

/** The complete ledger — a real payment is real wherever it happened. */
const MONEY = [
  'fresh_collective_revenue_cents',
  'processing_costs_cents',
  'contribution_after_processing_cents',
  'outstanding_payouts_cents',
]

const LEARNING = ['wb_eligible_creators', 'wb_creator_participation']

/** Production trends. */
const TRENDS = [
  'unique_members',
  'active_members',
  'members_joined',
  'gathering_attendees',
  'pathway_participants',
  'conversation_contributors',
]

/** The ledger's own trend, so the money chart is not production-only. */
const MONEY_TRENDS = [
  'gross_collective_sales_cents',
  'fresh_collective_revenue_cents',
]

const INK = FC_INK.heading
const INK_MUTED = FC_INK.muted
const CHART_H = 170

export default function OverviewPage() {
  const [range, setRange] = useState<HistoryRangeKey>('last_3_months')
  const [grouping, setGrouping] = useState<Grouping>('weekly')

  // The same key drives the figures and the charts.
  const headline = useMetrics(HEADLINE, range, 'production')
  const money = useMetrics(MONEY, range, 'all')
  const learning = useMetrics(LEARNING, range, 'all')
  const trends = useHistory(TRENDS, range, grouping, 'production')
  const ledger = useHistory(MONEY_TRENDS, range, grouping, 'all')
  const creators = useCreators()
  const health = useHealth()

  const previousLabel = headline.data?.comparison?.label ?? null

  return (
    <InsightsShell
      title="Overview"
      intro="How Fresh Collective is performing, what is changing, and what needs attention."
    >
      <HistoryControls
        range={range}
        grouping={grouping}
        population="production"
        onRange={setRange}
        onGrouping={setGrouping}
        options={trends.data?.options}
        disabled={trends.loading}
      />

      {headline.error && <Problem message={headline.error} />}

      {/* Four compact figures. Three are snapshots and say so. */}
      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          metric={pick(headline.data, 'unique_members')}
          previous={pickPrevious(headline.data, 'unique_members')}
          previousLabel={previousLabel}
          hue="navy"
          snapshot
          href="/admin/insights/growth"
        />
        <Tile
          metric={pick(headline.data, 'active_collectives')}
          hue="teal"
          snapshot
          href="/admin/insights/collectives"
        />
        <Tile
          metric={pick(headline.data, 'creator_accounts')}
          previous={pickPrevious(headline.data, 'creator_accounts')}
          previousLabel={previousLabel}
          hue="gold"
          snapshot
          href="/admin/insights/creators"
        />
        <Tile
          metric={pick(money.data, 'fresh_collective_revenue_cents')}
          previous={pickPrevious(money.data, 'fresh_collective_revenue_cents')}
          previousLabel={previousLabel}
          hue="watermelon"
          scope="complete ledger"
          href="/admin/insights/money"
        />
      </div>

      {trends.error && <Problem message={trends.error} />}

      <Row>
        <HistoryPanel
          title="Membership growth"
          explanation="Distinct people holding a Production membership at the end of each period."
          data={trends.data}
          keys={['unique_members']}
          kind="line"
          hues={['navy']}
          height={CHART_H}
          footnote="An end-of-period state, never a sum of its days."
        />
        <HistoryPanel
          title="Participation over time"
          explanation="Distinct Production members who did something in each period."
          data={trends.data}
          keys={['active_members']}
          kind="line"
          hues={['teal']}
          height={CHART_H}
          footnote="People, not acts. Somebody who posted four times and attended a Gathering is one participating member."
        />
      </Row>

      <Row>
        <HistoryPanel
          title="New members"
          explanation="Distinct people who began a Production membership in each period."
          data={trends.data}
          keys={['members_joined']}
          kind="column"
          hues={['teal']}
          height={CHART_H}
          footnote="People, not memberships: somebody who joined three Collectives is one new member here and three in 'Memberships started' on Growth. Includes existing members joining an additional Collective — the split between them is on the figures table."
        />
        <HistoryPanel
          title="How people take part"
          explanation="Distinct people in each kind of activity."
          data={trends.data}
          keys={[
            'gathering_attendees',
            'pathway_participants',
            'conversation_contributors',
          ]}
          kind="line"
          hues={['gold', 'navy', 'watermelon']}
          height={CHART_H}
          footnote="All three count distinct people, so they are comparable — unlike bookings, steps and posts, which are different units. They overlap and must not be added: one person can attend a Gathering and post in the same period."
        />
      </Row>

      <Row>
        <HistoryPanel
          title="Gross sales against our own revenue"
          explanation="What members paid creators, and the platform's share of it."
          data={ledger.data}
          keys={['gross_collective_sales_cents', 'fresh_collective_revenue_cents']}
          kind="line"
          hues={['navy', 'teal']}
          height={CHART_H}
          footnote="One axis, deliberately: the distance between the lines is the point. Gross sales is money moved on creators' behalf and is mostly theirs; Fresh Collective revenue is the platform's fee plus creator plan fees. Stacking them would imply the whole of gross sales is ours. The complete ledger, unlike the Production charts above."
        />
        <Panel
          title="The creator journey"
          note="Each stage implies the ones before it, so a creator stands at one point."
          href="/admin/insights/creators"
          linkLabel="Creators"
        >
          <Funnel creators={creators} />
        </Panel>
      </Row>

      <Row>
        <Panel
          title="World Builders"
          note="The creator learning environment. Internal operations, so never added to the Production figures above."
          href="/admin/insights/world-builders"
          linkLabel="World Builders"
        >
          <Learning data={learning.data} />
        </Panel>
        <Panel
          title="Where the money goes"
          note="The complete ledger, for the selected period."
          href="/admin/insights/money"
          linkLabel="Money"
        >
          <Breakdown data={money.data} />
        </Panel>
      </Row>

      <Attention money={money.data} health={health} />
    </InsightsShell>
  )
}

/** Two panels across on a laptop, stacked below it. */
function Row({ children }: { children: React.ReactNode }) {
  return <div className="mt-4 grid gap-4 lg:grid-cols-2">{children}</div>
}

/**
 * A compact headline figure.
 *
 * White, not a block of saturated colour: on a page whose job is to
 * be chart-led, four solid tiles at the top take the attention the
 * plots should have. Colour appears as a rule down the left edge, in
 * the same hue the metric wears in the charts below, which is enough
 * to tie them together.
 */
function Tile({
  metric,
  previous,
  previousLabel,
  hue,
  snapshot = false,
  scope,
  href,
}: {
  metric: MetricValue | null
  previous?: MetricValue | null
  previousLabel?: string | null
  hue: InsightHue
  /** A state right now, not a total over the selected range. */
  snapshot?: boolean
  /** Named only when it differs from the rest of the row. */
  scope?: string
  href: string
}) {
  if (!metric) {
    return (
      <div
        className="min-w-0 rounded-xl p-4"
        style={{ background: '#FFFFFF', border: `1px solid ${SURFACE.cardEdge}` }}
      >
        <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
          Not available
        </p>
      </div>
    )
  }

  // The comparison the API already returned, rendered — never
  // recomputed here. See ``compactComparison``.
  const comparison = compactComparison(metric, previous, previousLabel ?? null)

  return (
    <Link
      href={href}
      className="group min-w-0 rounded-xl p-4 pl-[14px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
      style={{
        background: '#FFFFFF',
        border: `1px solid ${SURFACE.cardEdge}`,
        borderLeft: `3px solid ${HUE_MARK[hue]}`,
      }}
    >
      <p
        className="text-[12px] leading-snug font-semibold break-words"
        style={{ color: INK }}
      >
        {metric.definition.display_name}
      </p>
      <p
        className="mt-1 font-serif text-[24px] leading-none tabular-nums"
        style={{ color: INK }}
      >
        {metric.available ? formatValue(metric) : '—'}
      </p>
      <p className="mt-1.5 text-[11.5px] leading-snug" style={{ color: INK_MUTED }}>
        {snapshot ? 'right now' : scope ?? 'over the selected period'}
        {scope && snapshot ? ` · ${scope}` : ''}
      </p>
      {/*
        No comparison for a snapshot that cannot be reconstructed, and
        none when the previous period had no figure — an invented
        arrow is worse than none.
      */}
      {comparison && (
        <p className="mt-1 text-[11.5px]" style={{ color: INK_MUTED }}>
          {comparison}
        </p>
      )}
    </Link>
  )
}

/** A white panel, matching the chart panels beside it. */
function Panel({
  title,
  note,
  href,
  linkLabel,
  children,
}: {
  title: string
  note: string
  href: string
  linkLabel: string
  children: React.ReactNode
}) {
  return (
    <section
      // ``self-start`` so a short panel keeps its own height instead
      // of stretching to match the chart beside it. A half-empty
      // bordered box reads as something failing to load; white space
      // in the grid cell reads as layout.
      className="flex min-w-0 flex-col self-start rounded-2xl p-5"
      style={{ background: '#FFFFFF', border: `1px solid ${SURFACE.cardEdge}` }}
    >
      <h4
        className="font-serif text-[15.5px] leading-tight"
        style={{ color: INK }}
      >
        {title}
      </h4>
      <p className="mt-1 max-w-[62ch] text-[12.5px]" style={{ color: INK_MUTED }}>
        {note}
      </p>
      <div className="mt-4">{children}</div>
      <p className="mt-4 text-[12.5px]">
        <Link
          href={href}
          className="rounded underline decoration-dotted underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
          style={{ color: INK_MUTED }}
        >
          View {linkLabel} details
        </Link>
      </p>
    </section>
  )
}

/**
 * The creator journey as a compact bar per stage.
 *
 * Uses the Creators dashboard's own ``stageCounts``, so there is one
 * funnel calculation on the platform rather than two that can drift.
 */
function Funnel({ creators }: { creators: Creator[] | null }) {
  if (creators === null) {
    return (
      <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
        Loading the journey…
      </p>
    )
  }
  const stages = stageCounts(creators)
  const total = stages[0]?.reached ?? 0
  if (total === 0) {
    return (
      <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
        No creators in this classification yet.
      </p>
    )
  }

  return (
    <ol className="m-0 list-none space-y-2 p-0">
      {stages.map((s) => (
        <li key={s.key} className="min-w-0">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[12.5px]" style={{ color: INK }}>
              {s.label}
            </span>
            <span
              className="text-[13px] tabular-nums"
              style={{ color: INK, fontWeight: 600 }}
            >
              {formatCount(s.reached)}
            </span>
          </div>
          <div
            className="mt-1 h-[7px] w-full overflow-hidden rounded-full"
            style={{ background: 'rgba(15, 30, 55, 0.07)' }}
          >
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.max(2, (s.reached / total) * 100)}%`,
                background: HUE_MARK.teal,
              }}
            />
          </div>
        </li>
      ))}
    </ol>
  )
}

/** Eligibility, and the smaller number who actually took part. */
function Learning({ data }: { data: MetricResult | null }) {
  const eligible = pick(data, 'wb_eligible_creators')
  const taking = pick(data, 'wb_creator_participation')
  if (!eligible || !taking) {
    return (
      <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
        Loading…
      </p>
    )
  }
  const total = eligible.value ?? 0
  const part = taking.value ?? 0

  return (
    <div>
      <div className="flex items-baseline gap-6">
        <Figure label="Eligible creators" value={formatValue(eligible)} />
        <Figure label="Took part" value={formatValue(taking)} />
      </div>
      <div
        className="mt-3 h-[9px] w-full overflow-hidden rounded-full"
        style={{ background: 'rgba(15, 30, 55, 0.07)' }}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: total > 0 ? `${Math.min(100, (part / total) * 100)}%` : '0%',
            background: HUE_MARK.teal,
          }}
        />
      </div>
      <p className="mt-2 text-[11.5px] leading-snug" style={{ color: INK_MUTED }}>
        Access is granted automatically to every eligible creator, so joining
        is not a step anybody chooses — the gap between these two is the
        thing worth watching. Taking part is not completing.
      </p>
    </div>
  )
}

/** Revenue, what it cost, and what was left. */
function Breakdown({ data }: { data: MetricResult | null }) {
  if (!data) {
    return (
      <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
        Loading…
      </p>
    )
  }
  const rows: [string, string, MetricValue | null][] = [
    ['Platform revenue', HUE_MARK.teal, pick(data, 'fresh_collective_revenue_cents')],
    ['Processing costs', HUE_MARK.gold, pick(data, 'processing_costs_cents')],
    [
      'Contribution after processing',
      HUE_MARK.navy,
      pick(data, 'contribution_after_processing_cents'),
    ],
  ]
  return (
    <>
      <dl className="m-0 space-y-2.5">
        {rows.map(([label, colour, metric]) => (
          <div key={label} className="flex items-baseline justify-between gap-3">
            <dt className="flex min-w-0 items-baseline gap-2 text-[12.5px]" style={{ color: INK }}>
              <span
                aria-hidden="true"
                className="inline-block h-[7px] w-[7px] shrink-0 rounded-full"
                style={{ background: colour }}
              />
              <span className="min-w-0">{label}</span>
            </dt>
            <dd
              className="m-0 shrink-0 text-[14px] tabular-nums"
              style={{ color: INK, fontWeight: 600 }}
            >
              {metric && metric.available ? formatValue(metric) : '—'}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[11.5px] leading-snug" style={{ color: INK_MUTED }}>
        Contribution is revenue less Stripe&rsquo;s fees. It is not profit —
        nothing it takes to run Fresh Collective is in it.
      </p>
    </>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11.5px]" style={{ color: INK_MUTED }}>
        {label}
      </p>
      <p
        className="font-serif text-[22px] leading-none tabular-nums"
        style={{ color: INK }}
      >
        {value}
      </p>
    </div>
  )
}

/**
 * What actually needs attention — at the foot, and usually empty.
 *
 * **An outstanding balance is not an alert.** Money a creator has
 * earned and not yet been sent is the normal state of a payouts
 * ledger, and the balance against founder-operated Collectives is
 * Fresh Collective owing itself: listing either as something to act
 * on teaches a caretaker to ignore this section. Only a balance owed
 * to an *independent* creator is somebody else's money waiting.
 *
 * Nothing here is inferred. A dip in growth or participation is not
 * a warning, and there is no overall health score.
 */
function Attention({
  money,
  health,
}: {
  money: MetricResult | null
  health: ReportingHealth | null
}) {
  const items: {
    tone: 'alert' | 'gold' | 'navy'
    title: string
    detail: string
    href: string
    action: string
    emphasis?: boolean
  }[] = []

  const split = outstandingBreakdown(pick(money, 'outstanding_payouts_cents'))
  if (split && split.externalCents > 0) {
    items.push({
      tone: 'navy',
      emphasis: true,
      title: `${formatMoney(split.externalCents)} owed to independent creators`,
      detail:
        'Earned and not yet transferred. Outstanding rather than overdue, ' +
        'and somebody else’s money.',
      href: '/admin/insights/money',
      action: 'See who it is owed to',
    })
  }

  if (health) {
    const state = describeHealth(health, false)
    if (state.hue === 'alert' || state.hue === 'gold') {
      items.push({
        tone: state.hue,
        title: state.label,
        detail:
          state.hue === 'alert'
            ? 'Reporting history is not being written as expected, so figures may be stale.'
            : 'Some recorded history could not be reconciled against the records behind it.',
        href: '/admin/insights/data-health',
        action: 'Open Data Health',
      })
    }
  }

  if (items.length === 0) {
    return (
      <div
        className="mt-5 rounded-xl px-4 py-3"
        style={{
          background: toneStyle('teal').bg,
          border: `1px solid ${toneStyle('teal').border}`,
        }}
      >
        <p className="text-[12.5px]" style={{ color: toneStyle('teal').text }}>
          Nothing needs attention. No independent creator is waiting on a
          payout and reporting history is being recorded cleanly.
        </p>
      </div>
    )
  }

  return (
    <section className="mt-6">
      <h2
        className="font-serif text-[15.5px] leading-tight"
        style={{ color: INK }}
      >
        Needs attention
      </h2>
      <div className="mt-2 grid gap-3 lg:grid-cols-2">
        {items.map((item) => {
          const tone = toneStyle(item.tone)
          const pink = item.emphasis
          return (
            <div
              key={item.title}
              className="min-w-0 rounded-xl p-4 break-words"
              style={
                pink
                  ? {
                      background: '#FFFFFF',
                      border: `1px solid ${HUE_UI.watermelon.border}`,
                      borderLeft: `3px solid ${EMPHASIS.obligation.surface}`,
                    }
                  : { background: tone.bg, border: `1px solid ${tone.border}` }
              }
            >
              <h3
                className="text-[13px] font-semibold leading-snug"
                style={{ color: pink ? HUE_UI.watermelon.text : tone.text }}
              >
                {item.title}
              </h3>
              <p
                className="mt-1 max-w-[70ch] text-[12px] leading-snug"
                style={{ color: FC_INK.body }}
              >
                {item.detail}
              </p>
              <Link
                href={item.href}
                className="mt-2 inline-block rounded text-[12px] underline decoration-dotted underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
                style={{ color: pink ? HUE_UI.watermelon.text : tone.text }}
              >
                {item.action}
              </Link>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function useCreators() {
  const [creators, setCreators] = useState<Creator[] | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    fetchCreators('production', controller.signal)
      .then((rows) => {
        if (!cancelled) setCreators(rows)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [])
  return creators
}

function useHealth() {
  const [health, setHealth] = useState<ReportingHealth | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    fetchHealth(controller.signal)
      .then((h) => {
        if (!cancelled) setHealth(h)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [])
  return health
}

function Problem({ message }: { message: string }) {
  return (
    <div
      className="mt-4 rounded-xl p-4"
      style={{
        background: STATUS.error.bg,
        border: `1px solid ${STATUS.error.border}`,
      }}
    >
      <p className="text-[13px]" style={{ color: STATUS.error.fg }}>
        {message}
      </p>
    </div>
  )
}
