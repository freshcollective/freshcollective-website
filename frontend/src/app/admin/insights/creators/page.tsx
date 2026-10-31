'use client'

import { useEffect, useState } from 'react'

import {
  CreatorJourney,
  CreatorTable,
} from '@/components/admin/insights/CreatorJourney'
import { HistoryControls } from '@/components/admin/insights/HistoryControls'
import { HistoryPanel } from '@/components/admin/insights/HistoryPanel'
import { InsightCard } from '@/components/admin/insights/InsightCard'
import { InsightsShell } from '@/components/admin/insights/InsightsShell'
import { PeriodSelect } from '@/components/admin/insights/PeriodSelect'
import { useHistory } from '@/components/admin/insights/useHistory'
import { useMetrics } from '@/components/admin/insights/useMetrics'
import {
  type MetricResult,
  type PeriodKey,
  formatMoney,
  pick,
} from '@/lib/insights'
import {
  type Creator,
  type Grouping,
  type HistoryRangeKey,
  type PopulationKey,
  fetchCreators,
} from '@/lib/insights-history'

/**
 * Creators — who is building here, and how far they get.
 *
 * The page is a journey rather than a league table, and the difference
 * is deliberate. Fresh Collective has one genuine external creator;
 * ranking her against two founder-operated Collectives would say
 * nothing true about either. So the charts count creators at each
 * stage, the table separates independent from founder-operated, and
 * nothing anywhere produces a score.
 *
 * Publishing is absent from the funnel on purpose. It is the obvious
 * fifth stage and ``spaces.status`` has no history behind it, so a
 * past date has no honest answer — see ``app.reporting.creators``. The
 * observed Collective counts carry that question, with the limitation
 * already stated.
 */

const HISTORY_KEYS = [
  'creator_accounts',
  'creators_with_a_collective',
  'creators_with_a_member',
  'creators_earning',
  'creators_registered',
]

const EARNINGS_KEYS = ['creator_earnings_cents', 'paid_out_cents']

/** Live questions: what exists now, not what existed in a closed period. */
const STATUS_KEYS = ['active_collectives', 'draft_collectives']

const CARD_KEYS = [
  'registered_creators',
  'active_creators',
  'creator_earnings_cents',
  'paid_out_cents',
  'outstanding_payouts_cents',
  'subscription_revenue_cents',
]

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

export default function CreatorsPage() {
  const [range, setRange] = useState<HistoryRangeKey>('last_12_months')
  const [grouping, setGrouping] = useState<Grouping>('monthly')
  const [population, setPopulation] = useState<PopulationKey>('production')
  const [creators, setCreators] = useState<Creator[]>([])
  const [listError, setListError] = useState<string | null>(null)

  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const { data: cards, error: cardError, loading } = useMetrics(
    CARD_KEYS, period, population,
  )
  const { data: status } = useMetrics(STATUS_KEYS, 'all_time', population)

  const history = useHistory(
    [...HISTORY_KEYS, ...EARNINGS_KEYS],
    range,
    grouping,
    population,
  )

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    fetchCreators(population, controller.signal)
      .then((rows) => {
        if (!cancelled) {
          setCreators(rows)
          setListError(null)
        }
      })
      .catch((e: Error) => {
        if (cancelled || e.name === 'AbortError') return
        setListError(e.message)
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [population])

  return (
    <InsightsShell
      title="Creators"
      intro="Who is building here, how far they get, and what they earn."
    >
      <HistoryControls
        range={range}
        grouping={grouping}
        population={population}
        onRange={setRange}
        onGrouping={setGrouping}
        onPopulation={setPopulation}
        options={history.data?.options}
        disabled={history.loading}
        populationNote={history.data?.population.note}
      />

      {listError && <Problem message={listError} />}
      {history.error && <Problem message={history.error} />}

      <div className="space-y-5">
        <CreatorJourney creators={creators} />

        <HistoryPanel
          prominent
          title="Milestones reached, over time"
          explanation="How many creators had reached each stage by the end of each period — cumulative, not new activity. A creator who started earning in March is still counted in October. The gaps between the lines are where creators stop."
          data={history.data}
          keys={[
            'creator_accounts',
            'creators_with_a_collective',
            'creators_with_a_member',
            'creators_earning',
          ]}
          kind="line"
          hues={['navy', 'teal', 'gold', 'coral']}
          footnote="Each line counts people and each stage implies the ones before it, so the lines narrow rather than add up and a creator with three Collectives is one creator throughout. All four are snapshots — a milestone already reached stays reached, which is why these lines only climb. The 'Creators registered' chart below counts something different: arrivals within each period, which rise and fall. The first stage counts anybody operating a Collective whatever their account role, so founder-operated Collectives are included; the table further down separates them. Publishing is not a stage here: a Collective's status is stored as one value with no history, so a past date has no honest answer."
        />
      </div>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          New arrivals in each period
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          <strong style={{ color: INK }}>Not the same thing as the chart
          above.</strong>{' '}
          That one counts milestones already reached and therefore only
          climbs; this counts creators who arrived <em>during</em> each
          period, so it rises and falls. A quiet month here is a quiet month
          for recruitment, not a loss of creators.
        </p>
        <HistoryPanel
          title="Creators registered"
          explanation="Creator accounts that came into being in each period. A flow — each column is its own period's arrivals, and the columns add up over time."
          data={history.data}
          keys={['creators_registered']}
          kind="column"
          hues={['navy']}
          footnote="Somebody who signs up and builds nothing still counts here, which is the point: the gap between this and 'Creators with a Collective' above is the first step of the journey."
        />
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          What creators earn
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Earned and paid, platform-wide. The Money page holds the full
          reconciliation; this is the creator&rsquo;s side of it.
        </p>
        <HistoryPanel
          title="Creator earnings and payouts"
          explanation="What creators earned in each period, beside what was actually transferred to them."
          data={history.data}
          keys={['creator_earnings_cents', 'paid_out_cents']}
          kind="column"
          hues={['teal', 'navy']}
          footnote="Earnings are net of refunds reversed against the creator's share and are dated by settlement; payouts are dated by when they were marked paid. The two are not expected to match, and a gap between them is an obligation rather than an error."
        />
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Who they are
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Every creator in this classification, with the furthest stage they
          have reached. Independent creators and founder-operated Collectives
          are listed separately rather than ranked together.
        </p>
        <CreatorTable creators={creators} />
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          The figures behind them
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          With their own period, chosen below.
        </p>

        <div className="mb-6">
          <PeriodSelect value={period} onChange={setPeriod} disabled={loading} />
        </div>

        {cardError && <Problem message={cardError} />}
        {loading && !cards && <Waiting />}

        {status && (
          <Band
            title="Collectives right now"
            note="A count at this moment, whichever period is selected above. Status is stored as one value with no history behind it, so a past date genuinely has no answer — these do not follow the period."
          >
            <InsightCard
              metric={pick(status, 'active_collectives')}
              hue="teal"
              caption="published and open"
            />
            <InsightCard
              metric={pick(status, 'draft_collectives')}
              hue="navy"
              caption="built but not yet opened"
            />
          </Band>
        )}

        {cards && (
          <>
            <Band
              title="Creators"
              note="Accounts and activity across the selected period."
            >
              <InsightCard
                metric={pick(cards, 'registered_creators')}
                hue="navy"
                caption="creator accounts in existence"
              />
              <InsightCard
                metric={pick(cards, 'active_creators')}
                hue="teal"
                caption="creators who did something in the period"
              />
            </Band>

            <Band
              title={`Earned and paid in ${cards.period.label.toLowerCase()}`}
              note="Figures for the selected period. Both are flows — money that moved during it."
            >
              <InsightCard
                metric={pick(cards, 'creator_earnings_cents')}
                hue="navy"
                caption="earned by creators in this period"
              />
              <InsightCard
                metric={pick(cards, 'paid_out_cents')}
                hue="teal"
                caption="actually transferred in this period"
              />
              <InsightCard
                metric={pick(cards, 'subscription_revenue_cents')}
                hue="gold"
                caption="what creators paid us for their plans"
              />
            </Band>

            <WhoseEarnings data={cards} />

            <Band
              title="Owed right now"
              note="A balance at this moment, not a period figure — it does not belong beside the figures above and is not comparable with them. A reporting period does not narrow it."
            >
              <InsightCard
                metric={pick(cards, 'outstanding_payouts_cents')}
                hue={
                  (pick(cards, 'outstanding_payouts_cents')?.value ?? 0) > 0
                    ? 'coral'
                    : 'navy'
                }
                caption="earned by creators and not yet transferred"
              />
              <WhoIsOwed data={cards} />
            </Band>
          </>
        )}
      </section>
    </InsightsShell>
  )
}

/**
 * Whose earnings those are.
 *
 * "Creators earned $933" and "external creators earned $933" are
 * different claims on a platform whose founder operates two of its
 * Collectives, and the single figure above answers the first while
 * being read as the second. The split comes from the metric's own
 * qualifiers, so the page does no arithmetic — it reports a division
 * the registry made.
 */
function WhoseEarnings({ data }: { data: MetricResult }) {
  const metric = pick(data, 'creator_earnings_cents')
  const split = metric?.qualifiers?.by_operator_cents as
    | { founder_operated: number; independent: number }
    | undefined
  if (!metric?.available || !split) return null
  const total = split.founder_operated + split.independent
  if (total === 0) return null

  return (
    <div
      className="mb-8 rounded-2xl p-5"
      style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
    >
      <h4 className="font-serif text-[15px]" style={{ color: INK }}>
        Whose earnings those are
      </h4>
      <dl className="mt-2.5 grid gap-2.5 sm:grid-cols-2">
        <Split
          label="Independent creators"
          cents={split.independent}
          note="People who came to Fresh Collective and built something. This is the figure that says what external creators are making."
        />
        <Split
          label="Founder-operated Collectives"
          cents={split.founder_operated}
          note="Real earnings, and Fresh Collective's own. Counted separately because including them in the first figure would overstate what the platform earns for other people."
        />
      </dl>
      <p
        className="mt-2.5 text-[12px] leading-snug"
        style={{ color: INK_MUTED, fontFamily: 'Georgia, serif', fontStyle: 'italic' }}
      >
        {String(metric.qualifiers?.operator_note ?? '')}
      </p>
    </div>
  )
}

/** The same division, for the balance rather than the period. */
function WhoIsOwed({ data }: { data: MetricResult }) {
  const metric = pick(data, 'outstanding_payouts_cents')
  const q = metric?.qualifiers ?? {}
  const external = q.owed_to_external_creators_cents
  const founder = q.owed_to_founder_operated_collectives_cents
  if (typeof external !== 'number' || typeof founder !== 'number') return null
  return (
    <div
      className="rounded-2xl p-5 sm:col-span-2 lg:col-span-3"
      style={{
        background: 'rgba(56, 160, 158, 0.06)',
        border: '1px solid rgba(56, 160, 158, 0.22)',
      }}
    >
      <dl className="grid gap-2.5 sm:grid-cols-2">
        <Split
          label="Owed to independent creators"
          cents={external}
          note="A genuine obligation to somebody else."
        />
        <Split
          label="Owed to founder-operated Collectives"
          cents={founder}
          note="Fresh Collective owing itself. Earned and unpaid as recorded, not treated as settled."
        />
      </dl>
    </div>
  )
}

function Split({
  label,
  cents,
  note,
}: {
  label: string
  cents: number
  note: string
}) {
  return (
    <div>
      <dt className="text-[12.5px]" style={{ color: INK_MUTED }}>
        {label}
      </dt>
      <dd
        className="m-0 text-[18px] tabular-nums"
        style={{ color: INK, fontFamily: 'Georgia, serif' }}
      >
        {formatMoney(cents)}
      </dd>
      <p className="mt-0.5 text-[11.5px] leading-snug" style={{ color: INK_MUTED }}>
        {note}
      </p>
    </div>
  )
}

function Band({
  title,
  note,
  children,
}: {
  title: string
  note: string
  children: React.ReactNode
}) {
  return (
    <section className="mb-8">
      <h4 className="font-serif text-[16px] leading-tight" style={{ color: INK }}>
        {title}
      </h4>
      <p className="mb-3 mt-1 max-w-[72ch] text-[12.5px]" style={{ color: INK_MUTED }}>
        {note}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
    </section>
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
        background: 'rgba(214, 96, 87, 0.06)',
        border: '1px solid rgba(214, 96, 87, 0.28)',
      }}
    >
      <p className="text-[13.5px]" style={{ color: '#a63c30' }}>
        {message}
      </p>
    </div>
  )
}
