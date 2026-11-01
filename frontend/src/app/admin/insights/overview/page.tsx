'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { HistoryControls } from '@/components/admin/insights/HistoryControls'
import { HistoryPanel } from '@/components/admin/insights/HistoryPanel'
import { CardNote, InsightCard } from '@/components/admin/insights/InsightCard'
import {
  CardGroup,
  CardSurfaceScope,
  InsightsSection,
} from '@/components/admin/insights/InsightsSection'
import { InsightsShell } from '@/components/admin/insights/InsightsShell'
import { PeriodSelect } from '@/components/admin/insights/PeriodSelect'
import { useHistory } from '@/components/admin/insights/useHistory'
import { useMetrics } from '@/components/admin/insights/useMetrics'
import {
  type MetricResult,
  type PeriodKey,
  type ReportingHealth,
  describeHealth,
  fetchHealth,
  formatCount,
  formatMoney,
  outstandingBreakdown,
  pick,
  pickPrevious,
} from '@/lib/insights'
import type { Grouping, HistoryRangeKey } from '@/lib/insights-history'
import {
  CARD,
  INK as FC_INK,
  STATUS,
  surfaceForGroup,
  toneStyle,
} from '@/lib/insights-palette'

/**
 * World Insights Overview — how Fresh Collective is doing.
 *
 * The starting point for the seven dashboards behind it, not an
 * eighth collection of every metric. Every figure here is the same
 * registry metric the detailed page uses, asked with the same
 * population, so the Overview and the dashboard it links to cannot
 * disagree: nothing is recomputed in the browser.
 *
 * One population does not fit the page
 * ------------------------------------
 * The hardest thing to get right here is that the sections ask
 * different questions and therefore need different populations, and
 * applying one filter to all of them would be wrong in both
 * directions:
 *
 *   members, Collectives, participation  production
 *   money                                the complete ledger
 *   World Builders                       internal operations
 *
 * Narrowing money to production would hide real Stripe movements that
 * happened in a demonstration Collective; widening membership to the
 * whole ledger would count test accounts as people who joined. So
 * each band fetches its own population and says which one it used —
 * see ``ScopeNote``.
 */

/** Production: people, Collectives and participation. */
const AT_A_GLANCE = [
  'unique_members',
  'active_collectives',
  'active_creators',
  'members_joined',
  'participation_rate',
]

/** The complete ledger: a real payment is real wherever it happened. */
const MONEY = [
  'fresh_collective_revenue_cents',
  'gross_collective_sales_cents',
  'processing_costs_cents',
  'contribution_after_processing_cents',
  'outstanding_payouts_cents',
]

/** Production, matching the Creators dashboard's own default. */
const CREATORS = [
  'creator_accounts',
  'creators_with_a_collective',
  'creators_with_a_member',
  'creators_earning',
]

/** World Builders is internal operations, so it is asked unfiltered. */
const LEARNING = ['wb_creator_participation']

const TREND_KEYS = ['unique_members', 'active_members']

const INK_MUTED = FC_INK.muted

export default function OverviewPage() {
  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const [range, setRange] = useState<HistoryRangeKey>('last_3_months')
  const [grouping, setGrouping] = useState<Grouping>('weekly')

  const production = useMetrics(AT_A_GLANCE, period, 'production')
  const money = useMetrics(MONEY, period, 'all')
  const creators = useMetrics(CREATORS, period, 'production')
  const learning = useMetrics(LEARNING, period, 'all')
  const history = useHistory(TREND_KEYS, range, grouping, 'production')
  const health = useHealth()

  const previousLabel = production.data?.comparison?.label ?? null

  return (
    <InsightsShell
      title="Overview"
      intro="How Fresh Collective is performing, what is changing, and what needs attention."
    >
      <Attention money={money.data} health={health} />

      <InsightsSection
        lead
        title="Fresh Collective today"
        intro="The figures a caretaker checks first. Each one is the same measure the detailed dashboard uses."
      >
        <div className="mb-5">
          <PeriodSelect
            value={period}
            onChange={setPeriod}
            disabled={production.loading}
          />
        </div>

        {production.error && <Problem message={production.error} />}
        {production.loading && !production.data && <Waiting />}

        {production.data && (
          <CardGroup
            surface={surfaceForGroup(0)}
            columns={3}
            title="People and communities"
            note="Production activity only — genuine Collectives, excluding accounts classified test or demonstration."
          >
            <InsightCard
              metric={pick(production.data, 'unique_members')}
              previous={pickPrevious(production.data, 'unique_members')}
              previousLabel={previousLabel}
              hue="navy"
              caption="people, counted once each"
            />
            <InsightCard
              metric={pick(production.data, 'active_collectives')}
              hue="navy"
              caption="published and open"
            />
            <InsightCard
              metric={pick(production.data, 'active_creators')}
              previous={pickPrevious(production.data, 'active_creators')}
              previousLabel={previousLabel}
              hue="teal"
              caption="creators who did something in the period"
            />
            <InsightCard
              metric={pick(production.data, 'members_joined')}
              previous={pickPrevious(production.data, 'members_joined')}
              previousLabel={previousLabel}
              hue="teal"
              caption="people who joined, counted once each"
            />
            <InsightCard
              metric={pick(production.data, 'participation_rate')}
              previous={pickPrevious(production.data, 'participation_rate')}
              previousLabel={previousLabel}
              hue="teal"
              caption="share of members taking part"
            />
            {money.data && (
              <RevenueCard data={money.data} previousLabel={previousLabel} />
            )}
          </CardGroup>
        )}

        <DeeperLinks
          links={[
            ['Growth', '/admin/insights/growth'],
            ['Participation', '/admin/insights/participation'],
          ]}
        />
      </InsightsSection>

      <InsightsSection
        title="Joining and taking part"
        intro="Whether the number of people arriving and the number actually participating are moving together."
      >
        <HistoryControls
          range={range}
          grouping={grouping}
          population="production"
          onRange={setRange}
          onGrouping={setGrouping}
          options={history.data?.options}
          disabled={history.loading}
        />

        {history.error && <Problem message={history.error} />}

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <HistoryPanel
            title="Membership over time"
            explanation="Distinct people holding a membership at the end of each period."
            data={history.data}
            keys={['unique_members']}
            kind="line"
            hues={['navy']}
            footnote="An end-of-period state, so a weekly figure is where things stood when the week closed — never a sum of its days."
          />
          <HistoryPanel
            title="Participation over time"
            explanation="Distinct members who did something in each period."
            data={history.data}
            keys={['active_members']}
            kind="line"
            hues={['teal']}
            footnote="People, not acts. Somebody who posted four times and attended a Gathering is one participating member."
          />
        </div>
      </InsightsSection>

      <InsightsSection
        title="Money"
        intro="The complete ledger, whatever each Collective's classification — a real Stripe movement is real wherever it happened."
      >
        {money.error && <Problem message={money.error} />}
        {money.data && (
          <>
            <CardGroup
              surface={surfaceForGroup(1)}
              title="What came in, and whose it is"
              note="Fresh Collective's own revenue is a fraction of gross Collective sales; most of that larger figure is creators' money."
            >
              <InsightCard
                metric={pick(money.data, 'gross_collective_sales_cents')}
                hue="navy"
                caption="what members paid creators — moved on their behalf"
              />
              <InsightCard
                metric={pick(money.data, 'fresh_collective_revenue_cents')}
                hue="teal"
                caption="platform fees plus creator plan fees"
              />
              <InsightCard
                metric={pick(money.data, 'processing_costs_cents')}
                hue="gold"
                caption="Stripe's fees, which we absorb"
              />
              <InsightCard
                metric={pick(money.data, 'contribution_after_processing_cents')}
                hue="navy"
                caption="our revenue less processing — not profit"
              />
              <InsightCard
                metric={pick(money.data, 'outstanding_payouts_cents')}
                hue="navy"
                // Outstanding, not overdue: earned and not yet
                // transferred is the normal state of a payouts balance.
                emphasis={
                  (pick(money.data, 'outstanding_payouts_cents')?.value ?? 0) > 0
                    ? 'obligation'
                    : undefined
                }
                caption="earned by creators and not yet transferred"
              />
            </CardGroup>

            <CardSurfaceScope surface={surfaceForGroup(1)}>
              <OwedTo data={money.data} />
            </CardSurfaceScope>
          </>
        )}

        <DeeperLinks links={[['Money', '/admin/insights/money']]} />
      </InsightsSection>

      <InsightsSection
        title="The creator ecosystem"
        intro="Whether creators are arriving, building, and getting somewhere — not the whole journey, which has its own dashboard."
      >
        {creators.error && <Problem message={creators.error} />}
        {creators.data && (
          <CardGroup
            surface={surfaceForGroup(2)}
            title="Creators and how far they have got"
            note="Production Collectives, using the Creators dashboard's own definition — anybody operating a Collective counts, whatever their role."
          >
            <InsightCard
              metric={pick(creators.data, 'creator_accounts')}
              hue="navy"
              caption="operating a Collective, or holding a creator account"
            />
            <InsightCard
              metric={pick(creators.data, 'creators_with_a_collective')}
              hue="teal"
              caption="have built something"
            />
            <InsightCard
              metric={pick(creators.data, 'creators_with_a_member')}
              hue="teal"
              caption="somebody has arrived"
            />
            <InsightCard
              metric={pick(creators.data, 'creators_earning')}
              hue="gold"
              caption="have taken at least one payment"
            />
          </CardGroup>
        )}

        {learning.data && (
          <CardGroup
            surface={surfaceForGroup(3)}
            title="Learning in World Builders"
            note="World Builders is the creator learning environment and is classified internal operations, so it is asked unfiltered and never added to the Production figures above."
          >
            <InsightCard
              metric={pick(learning.data, 'wb_creator_participation')}
              hue="teal"
              caption="creators who did something there in the period"
            />
            <LearningSplit data={learning.data} />
          </CardGroup>
        )}

        <DeeperLinks
          links={[
            ['Creators', '/admin/insights/creators'],
            ['World Builders', '/admin/insights/world-builders'],
          ]}
        />
      </InsightsSection>
    </InsightsShell>
  )
}

/** Data Health, polled once. The indicator in the header shares it. */
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

/**
 * What actually needs attention — and nothing else.
 *
 * Two rules decide what may appear here. An item must have a state
 * somebody can act on, and it must be **true**, not inferred: a dip
 * in participation is not a warning, it is a Tuesday. There is
 * deliberately no overall health score, because a single number
 * hiding four unrelated facts is how a dashboard stops being read.
 *
 * The kinds are kept apart in the same way the emphasis cards are:
 * an outstanding balance is money owed and not yet due, which is the
 * normal state of a payouts ledger, and colouring it like a failed
 * run would teach a caretaker to ignore the colour that means
 * something broke.
 */
function Attention({
  money,
  health,
}: {
  money: MetricResult | null
  health: ReportingHealth | null
}) {
  const items: {
    tone: 'alert' | 'gold' | 'teal' | 'navy'
    title: string
    detail: string
    href: string
    action: string
  }[] = []

  const owed = pick(money, 'outstanding_payouts_cents')
  const split = outstandingBreakdown(owed)
  if (owed?.value && owed.value > 0 && split) {
    items.push({
      tone: 'navy',
      title: `${formatMoney(split.externalCents)} owed to independent creators`,
      detail:
        split.founderCents > 0
          ? `A further ${formatMoney(split.founderCents)} sits against ` +
            'founder-operated Collectives, which is Fresh Collective ' +
            'owing itself rather than an obligation to somebody else.'
          : 'Earned and not yet transferred. Outstanding, not overdue.',
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
        className="mb-6 rounded-2xl p-5"
        style={{
          background: toneStyle('teal').bg,
          border: `1px solid ${toneStyle('teal').border}`,
        }}
      >
        <p className="text-[13.5px]" style={{ color: toneStyle('teal').text }}>
          Nothing needs attention. No creator payouts are outstanding and
          reporting history is being recorded cleanly.
        </p>
      </div>
    )
  }

  return (
    <section className="mb-7">
      <h2
        className="font-serif text-[19px] leading-tight tracking-[-0.01em]"
        style={{ color: FC_INK.heading }}
      >
        Needs attention
      </h2>
      <p className="mb-3 mt-1 max-w-[72ch] text-[12.5px]" style={{ color: INK_MUTED }}>
        Only states somebody can act on. An ordinary dip in growth or
        participation is not listed here.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item) => {
          const tone = toneStyle(item.tone)
          return (
            <div
              key={item.title}
              className="min-w-0 rounded-2xl p-5 break-words"
              style={{ background: tone.bg, border: `1px solid ${tone.border}` }}
            >
              <h3
                className="text-[13.5px] font-semibold leading-snug"
                style={{ color: tone.text }}
              >
                {item.title}
              </h3>
              <p
                className="mt-1.5 max-w-[72ch] text-[12.5px]"
                style={{ color: FC_INK.body }}
              >
                {item.detail}
              </p>
              <Link
                href={item.href}
                className="mt-2.5 inline-block rounded text-[12.5px] underline decoration-dotted underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
                style={{ color: tone.text }}
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

/**
 * Fresh Collective's own revenue, sat among the production figures.
 *
 * Its population is different from every other card in that band —
 * the complete ledger rather than production — so it says so on the
 * card rather than relying on the band's note. A money figure
 * narrowed to production would quietly drop real Stripe movements.
 */
function RevenueCard({
  data,
  previousLabel,
}: {
  data: MetricResult
  previousLabel: string | null
}) {
  return (
    <InsightCard
      metric={pick(data, 'fresh_collective_revenue_cents')}
      previous={pickPrevious(data, 'fresh_collective_revenue_cents')}
      previousLabel={previousLabel}
      hue="gold"
      caption="platform fees and creator plans — the complete ledger"
    />
  )
}

/** Who the outstanding balance is owed to. Never treated as settled. */
function OwedTo({ data }: { data: MetricResult }) {
  const split = outstandingBreakdown(pick(data, 'outstanding_payouts_cents'))
  if (!split) return null
  if (split.externalCents === 0 && split.founderCents === 0) return null

  return (
    <CardNote accent="teal" span="mt-3">
      <dl className="grid gap-2.5 sm:grid-cols-2">
        <div>
          <dt className="text-[12.5px]" style={{ color: CARD.ink }}>
            Owed to independent creators
          </dt>
          <dd
            className="m-0 text-[18px] tabular-nums"
            style={{ color: CARD.ink, fontFamily: 'Georgia, serif' }}
          >
            {formatMoney(split.externalCents)}
          </dd>
          <p className="mt-0.5 text-[11.5px] leading-snug" style={{ color: CARD.ink }}>
            A genuine obligation to somebody else.
          </p>
        </div>
        <div>
          <dt className="text-[12.5px]" style={{ color: CARD.ink }}>
            Owed to founder-operated Collectives
          </dt>
          <dd
            className="m-0 text-[18px] tabular-nums"
            style={{ color: CARD.ink, fontFamily: 'Georgia, serif' }}
          >
            {formatMoney(split.founderCents)}
          </dd>
          <p className="mt-0.5 text-[11.5px] leading-snug" style={{ color: CARD.ink }}>
            Fresh Collective owing itself. Earned and unpaid as recorded, not
            treated as settled and not overdue to anybody.
          </p>
        </div>
      </dl>
    </CardNote>
  )
}

/** Independent against founder-operated, for World Builders use. */
function LearningSplit({ data }: { data: MetricResult }) {
  const metric = pick(data, 'wb_creator_participation')
  const q = metric?.qualifiers ?? {}
  const independent = q.independent
  const founder = q.founder_operated
  if (typeof independent !== 'number' || typeof founder !== 'number') return null

  return (
    <CardNote accent="teal" span="sm:col-span-2 lg:col-span-3">
      <p className="text-[13px]" style={{ color: CARD.ink }}>
        {formatCount(independent)}{' '}
        {independent === 1 ? 'independent creator' : 'independent creators'} and{' '}
        {formatCount(founder)} operating founder-run Collectives took part.
      </p>
      <p className="mt-2 text-[12.5px]" style={{ color: CARD.ink }}>
        Taking part is not completing: no reliable Pathway completion event is
        recorded, so nothing here says a creator finished anything.
      </p>
    </CardNote>
  )
}

/**
 * Where to go next.
 *
 * Plain links rather than whole-card targets: a metric card already
 * has a disclosure button inside it, and nesting that in a link
 * makes both harder to reach by keyboard and ambiguous to a screen
 * reader.
 */
function DeeperLinks({ links }: { links: [string, string][] }) {
  return (
    <p className="mt-1 flex flex-wrap gap-x-5 gap-y-1.5 text-[12.5px]">
      {links.map(([label, href]) => (
        <Link
          key={href}
          href={href}
          className="rounded underline decoration-dotted underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
          style={{ color: FC_INK.muted }}
        >
          View {label} details
        </Link>
      ))}
    </p>
  )
}

function Waiting() {
  return (
    <p className="py-10 text-center text-[13.5px]" style={{ color: INK_MUTED }}>
      Gathering the figures…
    </p>
  )
}

function Problem({ message }: { message: string }) {
  return (
    <div
      className="mb-5 rounded-2xl p-5"
      style={{
        background: STATUS.error.bg,
        border: `1px solid ${STATUS.error.border}`,
      }}
    >
      <p className="text-[13.5px]" style={{ color: STATUS.error.fg }}>
        {message}
      </p>
    </div>
  )
}
