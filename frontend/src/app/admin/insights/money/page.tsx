'use client'

import { useState } from 'react'

import { InsightCard } from '@/components/admin/insights/InsightCard'
import { InsightsShell } from '@/components/admin/insights/InsightsShell'
import { PeriodSelect } from '@/components/admin/insights/PeriodSelect'
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

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

export default function MoneyPage() {
  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const { data, error, loading } = useMetrics(KEYS, period)

  const prev = data?.comparison?.label ?? null

  return (
    <InsightsShell
      title="Money"
      intro="What Fresh Collective earns, what creators earn, and what has actually been paid."
    >
      <div className="mb-5">
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
              previous={pickPrevious(data, 'contribution_after_processing_cents')}
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

          <WhoIsOwedNote data={data} />

          <Band
            title="Money that went back"
            note="Counted on the day the refund happened, so a closed month's figures never change afterwards."
          >
            <InsightCard
              metric={pick(data, 'refunds_cents')}
              previous={pickPrevious(data, 'refunds_cents')}
              previousLabel={prev}
              hue={(pick(data, 'refunds_cents')?.value ?? 0) > 0 ? 'coral' : 'navy'}
              caption="returned to members"
            />
            <WhoseMoneyNote data={data} />
          </Band>
        </>
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
