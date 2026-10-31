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
  formatCount,
  pick,
  pickPrevious,
} from '@/lib/insights'
import type {
  Grouping,
  HistoryRangeKey,
  PopulationKey,
} from '@/lib/insights-history'

/**
 * Growth — who is arriving, and how fast.
 *
 * The page exists to keep three questions apart that a single "members"
 * figure used to blur: how many people have an account, how many of them
 * belong to a Collective, and how many memberships exist. A person in
 * three Collectives is one member and three memberships, and the old
 * role-derived count could say neither.
 *
 * Snapshots and flows are shown in separate bands for the same reason.
 * "Members right now" and "memberships started this month" answer
 * different questions, and putting them side by side invites somebody to
 * subtract one from the other.
 */

const SNAPSHOT_KEYS = [
  'unique_members',
  'total_memberships',
  'memberships_per_member',
  'multi_collective_members',
  'registered_users',
  'registered_creators',
  'total_collectives',
  'active_collectives',
]

const FLOW_KEYS = ['memberships_started']

const KEYS = [...SNAPSHOT_KEYS, ...FLOW_KEYS]

/**
 * The metrics the charts need, fetched in one request.
 *
 * Batched so every panel on the page resolves the same range and the
 * same bucket boundaries. Three panels fetching separately could each
 * land on a different "last completed day" if a request crossed
 * midnight in Sydney, and two charts disagreeing about where the week
 * ends is exactly the drift the shared reporting API exists to prevent.
 */
const HISTORY_KEYS = [
  'unique_members',
  'total_memberships',
  'memberships_started',
  'members_in_one_collective',
  'members_in_two_collectives',
  'members_in_three_plus_collectives',
]

const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

export default function GrowthPage() {
  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const [population, setPopulation] = useState<PopulationKey>('production')
  const { data, error, loading } = useMetrics(KEYS, period, population)

  // Growth reporting defaults to production: the question this page
  // asks is whether genuine communities are growing, and a test account
  // in a real Collective would answer it wrongly. The Money page
  // defaults the other way, to the complete ledger, because there the
  // default must never be a subset.
  const [range, setRange] = useState<HistoryRangeKey>('last_3_months')
  const [grouping, setGrouping] = useState<Grouping>('weekly')
  const history = useHistory(HISTORY_KEYS, range, grouping, population)

  const previousLabel = data?.comparison?.label ?? null

  return (
    <InsightsShell
      title="Growth"
      intro="Who has arrived, how many communities they belong to, and how that is changing."
    >
      {/*
        Charts first, figures underneath. The page answers "what has
        been happening" before "what exactly is it now" — the trend is
        the thing somebody opens this page for, and the cards are what
        they reach for once a line has raised a question.
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
          title="Membership growth"
          explanation="People and memberships side by side. Memberships climbing faster than people means members are finding a second and third Collective."
          data={history.data}
          keys={['unique_members', 'total_memberships']}
          kind="line"
          hues={['navy', 'teal']}
          footnote="Both are end-of-period states, so a weekly figure is where things stood when the week closed — never a sum of its days."
        />

        <HistoryPanel
          title="New memberships"
          explanation="Memberships that began in each period."
          data={history.data}
          keys={['memberships_started']}
          kind="column"
          hues={['teal']}
          footnote="This one does add up over time, which is why it is drawn as separate columns rather than joined into a line: each column is its own period's activity, not a running total."
        />

        <HistoryPanel
          title="How many Collectives people belong to"
          explanation="Every member sits in exactly one band, so the three stack to the total number of members at that date."
          data={history.data}
          keys={[
            'members_in_one_collective',
            'members_in_two_collectives',
            'members_in_three_plus_collectives',
          ]}
          kind="stacked"
          hues={['navy', 'teal', 'gold']}
          footnote="Worked out from membership join and removal dates rather than recorded at the time. A membership that ended before removal dates were stored is invisible here, which can place a member in a higher band than they belonged to on an early date."
        />
      </div>

      <section className="mt-12">
        <h3
          className="font-serif text-[17px] leading-tight"
          style={{ color: '#0C1826' }}
        >
          The figures behind them
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          These have their own period, chosen below and independent of the
          charts above — the charts answer what has been happening, these
          answer where things stand now.
        </p>

        <div className="mb-6">
          <PeriodSelect value={period} onChange={setPeriod} disabled={loading} />
        </div>

        {error && <Problem message={error} />}
        {loading && !data && <Waiting />}

        {data && (
          <>
            <Band
              title="Right now"
              note="A count at this moment, whichever period is selected above — these describe today, not a span of time."
            >
              <InsightCard
                metric={pick(data, 'unique_members')}
                hue="navy"
                caption="people, counted once each"
              />
              <InsightCard
                metric={pick(data, 'total_memberships')}
                hue="navy"
                caption="one per Collective someone has joined"
              />
              <InsightCard
                metric={pick(data, 'memberships_per_member')}
                hue="navy"
                caption="communities per person, on average"
              />
              <InsightCard
                metric={pick(data, 'multi_collective_members')}
                hue="teal"
                caption="people who have found more than one home here"
              />
            </Band>

            <Band
              title="The wider world"
              note="Accounts and Collectives in existence, whether or not anyone has joined anything."
            >
              <InsightCard
                metric={pick(data, 'registered_users')}
                hue="navy"
                caption="accounts, including creators"
              />
              <InsightCard
                metric={pick(data, 'registered_creators')}
                hue="teal"
                caption="people building something"
              />
              <InsightCard
                metric={pick(data, 'total_collectives')}
                hue="navy"
                caption="all Collectives, at any stage"
              />
              <InsightCard
                metric={pick(data, 'active_collectives')}
                hue="teal"
                caption="published and open"
              />
            </Band>

            <Band
              title={`What happened in ${data.period.label.toLowerCase()}`}
              note="A count across the selected period, so these do add up over time."
            >
              <InsightCard
                metric={pick(data, 'memberships_started')}
                previous={pickPrevious(data, 'memberships_started')}
                previousLabel={previousLabel}
                hue="teal"
                caption="new memberships, counting each Collective joined"
              />
              <OverlapNote data={data} />
            </Band>
          </>
        )}
      </section>
    </InsightsShell>
  )
}


/**
 * The one piece of written interpretation on the page.
 *
 * Membership overlap is the figure most likely to be misread as a
 * duplicate-counting bug, so it is explained in a sentence rather than
 * left as two numbers that look contradictory.
 */
function OverlapNote({ data }: { data: MetricResult }) {
  const members = pick(data, 'unique_members')?.value ?? null
  const memberships = pick(data, 'total_memberships')?.value ?? null
  const multi = pick(data, 'multi_collective_members')?.value ?? null
  if (members === null || memberships === null || multi === null) return null
  if (members === 0) return null

  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: 'rgba(56, 160, 158, 0.06)',
        border: '1px solid rgba(56, 160, 158, 0.22)',
      }}
    >
      <p className="text-[13px]" style={{ color: 'rgba(12, 24, 38, 0.78)' }}>
        {formatCount(members)} {members === 1 ? 'person holds' : 'people hold'}{' '}
        {formatCount(memberships)}{' '}
        {memberships === 1 ? 'membership' : 'memberships'} between them
        {multi > 0 ? (
          <>
            , and {formatCount(multi)} of {members === 1 ? 'them' : 'those people'}{' '}
            {multi === 1 ? 'belongs' : 'belong'} to more than one Collective.
          </>
        ) : (
          <>, each in a single Collective so far.</>
        )}
      </p>
      <p
        className="mt-2 text-[12.5px]"
        style={{
          color: INK_MUTED,
          fontFamily: 'Georgia, serif',
          fontStyle: 'italic',
        }}
      >
        Memberships outnumbering people is a good sign, not a double count.
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
      <h3
        className="font-serif text-[17px] leading-tight"
        style={{ color: '#0C1826' }}
      >
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
