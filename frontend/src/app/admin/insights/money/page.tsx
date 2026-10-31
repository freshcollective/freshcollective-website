'use client'

import { useState } from 'react'

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
  humaniseClass,
  outstandingBreakdown,
  pick,
  pickPrevious,
} from '@/lib/insights'
import type {
  Grouping,
  HistoryRangeKey,
  PopulationKey,
} from '@/lib/insights-history'

/**
 * Money — what comes in, and whose it is.
 *
 * The page is arranged around the distinction that matters most and is
 * easiest to lose: most of the money Fresh Collective processes is not
 * Fresh Collective's. Gross sales belong to creators; the platform keeps
 * a fee. So the bands are ordered by whose money it is, and the
 * platform's own revenue is never shown adjacent to volume without a
 * sentence saying which is which.
 *
 * Four different questions, kept apart:
 *
 *   volume      how much moved through the platform
 *   revenue     what Fresh Collective earned
 *   obligation  what creators have earned but not yet been paid
 *   cash        what has actually been transferred
 *
 * Contribution is labelled "after processing costs" everywhere it
 * appears, and never "profit" — no operating expenses are in it.
 */

const KEYS = [
  'gross_collective_sales_cents',
  'subscription_revenue_cents',
  'platform_fee_revenue_cents',
  'contribution_after_processing_cents',
  'processing_costs_cents',
  'creator_earnings_cents',
  'paid_out_cents',
  'outstanding_payouts_cents',
  'refunds_cents',
]

/**
 * The money series the charts draw, fetched together.
 *
 * One request so every panel shares one set of bucket boundaries — two
 * money charts disagreeing about where a month ends is the original
 * defect this whole reporting layer was built to end.
 */
const HISTORY_KEYS = [
  'platform_fee_revenue_cents',
  'subscription_revenue_cents',
  'gross_collective_sales_cents',
  'creator_earnings_cents',
  'paid_out_cents',
  'processing_costs_cents',
  'contribution_after_processing_cents',
  'refunds_cents',
]

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

export default function MoneyPage() {
  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const [population, setPopulation] = useState<PopulationKey>('all')
  const { data, error, loading } = useMetrics(KEYS, period, population)

  // The complete ledger is the default here, and that is a rule rather
  // than a preference: a money page whose default view silently omitted
  // real Stripe movements would misstate the business. Production is
  // one click away and announces itself as a subset. Growth defaults
  // the other way, because there a test account is noise.
  const [range, setRange] = useState<HistoryRangeKey>('last_3_months')
  const [grouping, setGrouping] = useState<Grouping>('weekly')
  const history = useHistory(HISTORY_KEYS, range, grouping, population)

  const prev = data?.comparison?.label ?? null

  return (
    <InsightsShell
      title="Money"
      intro="What Fresh Collective earns, what creators earn, and what has actually been paid."
    >
      {/*
        Charts first, figures underneath — and the ordering inside each
        half is the same one the page has always used: whose money it
        is. Our income, then the volume we moved for creators, then what
        went back. Putting gross sales first would put the biggest
        number at the top of a page about revenue, which is the
        misreading this page exists to prevent.
      */}
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

      {history.error && <Problem message={history.error} />}

      <div className="space-y-5">
        <HistoryPanel
          prominent
          title="Fresh Collective's own income"
          explanation="The two streams that are genuinely ours: the fee kept from member purchases, and what creators pay for their plans. Stacked, so the combined height is total income."
          data={history.data}
          keys={['platform_fee_revenue_cents', 'subscription_revenue_cents']}
          kind="stacked"
          hues={['teal', 'gold']}
          footnote="Attributed to the period the money arrived in, not the period a checkout happened to be created in. Payments that arrived before business-event recording began carry no observed settlement date and fall back to their creation date, which the chart reports as an approximation."
        />

        <HistoryPanel
          title="Gross Collective sales"
          explanation="Everything members paid creators, before any deduction. This is transaction volume, not Fresh Collective's income — most of it belongs to the creators who earned it."
          data={history.data}
          keys={['gross_collective_sales_cents']}
          kind="column"
          hues={['navy']}
          footnote="Read beside the income chart above, never as a substitute for it. The two answer different questions: how much moved through the platform, and how much of it was ours."
        />

        <HistoryPanel
          title="Creator earnings and payouts"
          explanation="What creators earned in each period, beside what was actually transferred to them. A gap between the two is an obligation, not an error."
          data={history.data}
          keys={['creator_earnings_cents', 'paid_out_cents']}
          kind="column"
          hues={['teal', 'navy']}
          footnote="Deliberately two series rather than one: earning is a period's trade and a payout is a cash movement with its own date, so the columns are not expected to match. Earnings are net of refunds reversed against the creator's share; payouts are counted on the date they were marked paid, which is why a period can show earnings with no payout beside them."
        />

        <HistoryPanel
          title="Processing costs and contribution"
          explanation="Stripe's fee against what Fresh Collective keeps after it. Contribution after processing costs is not profit — every operating expense sits outside it."
          data={history.data}
          keys={[
            'processing_costs_cents',
            'contribution_after_processing_cents',
          ]}
          kind="column"
          hues={['coral', 'teal']}
          footnote="Stripe does not report a fee until reconciliation reads it, and those payments are excluded rather than estimated — so a recent period's cost is a lower bound and its contribution correspondingly a little high."
        />

        <HistoryPanel
          title="Refunds"
          explanation="Money returned, counted in the period the refund happened rather than netted against the original sale."
          data={history.data}
          keys={['refunds_cents']}
          kind="column"
          hues={['coral']}
          footnote="Counting a refund on its own date is what keeps a closed month's revenue from moving afterwards. Only the most recent refund date is stored per transaction, so a payment refunded twice in different periods is attributed wholly to the later one. Refunds taken before that date was recorded cannot be placed in a period at all and appear as a gap rather than as a zero."
        />
      </div>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          The figures behind them
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Grouped by whose money it is, which is the distinction most
          easily lost: most of what Fresh Collective processes is not Fresh
          Collective&rsquo;s. These have their own period, chosen below.
        </p>

        <div className="mb-6">
          <PeriodSelect value={period} onChange={setPeriod} disabled={loading} />
        </div>

        {error && <Problem message={error} />}
        {loading && !data && <Waiting />}

        {data && (
          <>
            <Band
              title="Fresh Collective's own income"
              note="The two streams that are genuinely ours: the fee kept from member purchases, and what creators pay for their plans."
            >
              <InsightCard
                metric={pick(data, 'platform_fee_revenue_cents')}
                previous={pickPrevious(data, 'platform_fee_revenue_cents')}
                previousLabel={prev}
                hue="teal"
                caption="our share of what members paid creators"
              />
              <InsightCard
                metric={pick(data, 'subscription_revenue_cents')}
                previous={pickPrevious(data, 'subscription_revenue_cents')}
                previousLabel={prev}
                hue="teal"
                caption="creator plan fees paid to us"
              />
              <InsightCard
                metric={pick(data, 'processing_costs_cents')}
                previous={pickPrevious(data, 'processing_costs_cents')}
                previousLabel={prev}
                hue="gold"
                caption="Stripe's fees, which we absorb"
              />
              <InsightCard
                metric={pick(data, 'contribution_after_processing_cents')}
                previous={pickPrevious(
                  data,
                  'contribution_after_processing_cents',
                )}
                previousLabel={prev}
                hue="teal"
                caption="our income less processing — not profit"
              />
            </Band>

            <NotProfitNote />

            <Band
              title="Money we moved for creators"
              note="Volume, not income. Most of this belongs to the creators who earned it."
            >
              <InsightCard
                metric={pick(data, 'gross_collective_sales_cents')}
                previous={pickPrevious(data, 'gross_collective_sales_cents')}
                previousLabel={prev}
                hue="navy"
                caption="everything members paid, before any deduction"
              />
              <InsightCard
                metric={pick(data, 'creator_earnings_cents')}
                previous={pickPrevious(data, 'creator_earnings_cents')}
                previousLabel={prev}
                hue="navy"
                caption="what creators earned — owed, not yet sent"
              />
              <InsightCard
                metric={pick(data, 'paid_out_cents')}
                previous={pickPrevious(data, 'paid_out_cents')}
                previousLabel={prev}
                hue="teal"
                caption="actually transferred to creators"
              />
              <InsightCard
                metric={pick(data, 'outstanding_payouts_cents')}
                hue={
                  (pick(data, 'outstanding_payouts_cents')?.value ?? 0) > 0
                    ? 'coral'
                    : 'navy'
                }
                emphasiseValue={
                  (pick(data, 'outstanding_payouts_cents')?.value ?? 0) > 0
                }
                caption="owed to creators right now"
              />
            </Band>

            <Band
              title="Money that went back"
              note="Counted on the day the refund happened, so a closed month's figures never change afterwards."
            >
              <InsightCard
                metric={pick(data, 'refunds_cents')}
                previous={pickPrevious(data, 'refunds_cents')}
                previousLabel={prev}
                hue={
                  (pick(data, 'refunds_cents')?.value ?? 0) > 0 ? 'coral' : 'navy'
                }
                caption="returned to members"
              />
            </Band>
          </>
        )}
      </section>

      {data && (
        <section className="mt-12">
          <h3
            className="font-serif text-[17px] leading-tight"
            style={{ color: INK }}
          >
            Who is owed what
          </h3>
          <p
            className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
            style={{ color: INK_MUTED }}
          >
            The reconciliation behind the outstanding balance: who holds it,
            and what kind of activity it came from.
          </p>
          <WhoIsOwedNote data={data} />
          <div className="mt-4">
            <WhoseMoneyNote data={data} />
          </div>
        </section>
      )}
    </InsightsShell>
  )
}


/**
 * Stated once, prominently, rather than relying on a card caption.
 *
 * "Contribution" is the figure most likely to be mistaken for profit,
 * and the mistake would flatter the business. Better to say so plainly
 * than to hope the label carries it.
 */
function NotProfitNote() {
  return (
    <div
      className="mb-8 rounded-2xl p-4"
      style={{
        background: 'rgba(212, 176, 72, 0.08)',
        border: '1px solid rgba(212, 176, 72, 0.28)',
      }}
    >
      <p className="text-[12.5px]" style={{ color: '#8A6A15' }}>
        Contribution is income less Stripe&rsquo;s processing fees only. It is not
        profit — hosting, software, and everything else it takes to run Fresh
        Collective sit outside the platform and are not in this figure.
      </p>
    </div>
  )
}

/**
 * Who the outstanding balance is actually owed to.
 *
 * The figure that started all of this read $1,560 "outstanding to
 * creators" when every dollar of it belonged to Collectives the platform
 * owner runs. That is not a third-party obligation and reporting it as
 * one overstates what the business owes other people — but nor is it
 * settled, because no payout has been recorded against it. Both things
 * are true, so both are said.
 *
 * The classification line is shown only once an operator has assigned
 * reporting classes. Until then it would be a row of zeroes beside
 * "unclassified", which tells the reader nothing they cannot see.
 */
function WhoIsOwedNote({ data }: { data: MetricResult }) {
  const split = outstandingBreakdown(pick(data, 'outstanding_payouts_cents'))
  if (!split) return null
  if (split.externalCents === 0 && split.founderCents === 0) return null

  const classes = Object.entries(split.byClass).filter(
    ([name]) => name !== 'unclassified',
  )

  return (
    <div
      className="mb-8 rounded-2xl p-5"
      style={{
        background: 'rgba(56, 116, 180, 0.06)',
        border: '1px solid rgba(56, 116, 180, 0.22)',
      }}
    >
      <h4
        className="font-serif text-[15px] leading-tight"
        style={{ color: INK }}
      >
        Who that is owed to
      </h4>
      <dl className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Owed
          label="Independent creators"
          amount={split.externalCents}
          hint="A genuine obligation to somebody else."
        />
        <Owed
          label="Collectives you operate"
          amount={split.founderCents}
          hint="Fresh Collective owing itself. Earned and unpaid as recorded, not treated as settled."
        />
      </dl>
      {classes.length > 0 && (
        <p className="mt-3 text-[12.5px]" style={{ color: INK_MUTED }}>
          By activity:{' '}
          {classes
            .map(([name, cents]) => `${humaniseClass(name)} ${formatMoney(cents)}`)
            .join(' · ')}
        </p>
      )}
      <p
        className="mt-3 text-[12.5px]"
        style={{
          color: INK_MUTED,
          fontFamily: 'Georgia, serif',
          fontStyle: 'italic',
        }}
      >
        A Stripe payout into Fresh Collective&rsquo;s bank account is not a creator
        payout, so nothing here is cleared by one.
      </p>
    </div>
  )
}

function Owed({
  label,
  amount,
  hint,
}: {
  label: string
  amount: number
  hint: string
}) {
  return (
    <div>
      <dt className="text-[12.5px]" style={{ color: INK_MUTED }}>
        {label}
      </dt>
      <dd
        className="text-[19px] tabular-nums"
        style={{ color: INK, fontWeight: 600 }}
      >
        {formatMoney(amount)}
      </dd>
      <dd className="text-[11.5px]" style={{ color: 'rgba(12, 24, 38, 0.42)' }}>
        {hint}
      </dd>
    </div>
  )
}

/**
 * The whose-money-is-it sentence, written from the actual figures.
 *
 * The share Fresh Collective keeps is the thing a founder wants to know
 * and the thing a gross-volume number hides, so it is spelled out rather
 * than left to be divided mentally.
 */
function WhoseMoneyNote({ data }: { data: MetricResult }) {
  const gross = pick(data, 'gross_collective_sales_cents')?.value ?? 0
  const fee = pick(data, 'platform_fee_revenue_cents')?.value ?? 0
  const creators = pick(data, 'creator_earnings_cents')?.value ?? 0

  if (gross === 0) {
    return (
      <div
        className="rounded-2xl p-5"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
      >
        <p className="text-[13px]" style={{ color: INK_MUTED }}>
          No member purchases in this period, so there is nothing to divide up
          yet.
        </p>
      </div>
    )
  }

  const share = Math.round((fee / gross) * 100)
  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: 'rgba(56, 116, 180, 0.06)',
        border: '1px solid rgba(56, 116, 180, 0.22)',
      }}
    >
      <p className="text-[13px]" style={{ color: 'rgba(12, 24, 38, 0.78)' }}>
        Of {formatMoney(gross)} members paid, {formatMoney(creators)} is the
        creators&rsquo; and {formatMoney(fee)} is ours — about {share}%.
      </p>
      <p
        className="mt-2 text-[12.5px]"
        style={{
          color: INK_MUTED,
          fontFamily: 'Georgia, serif',
          fontStyle: 'italic',
        }}
      >
        The large number is the one that passes through; the small one is the
        one that stays.
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
      <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
        {title}
      </h3>
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
