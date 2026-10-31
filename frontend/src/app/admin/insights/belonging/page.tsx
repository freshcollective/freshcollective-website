'use client'

import { useState } from 'react'

import { CohortTable } from '@/components/admin/insights/CohortTable'
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
} from '@/lib/insights'
import type {
  CohortRow,
  Grouping,
  HistoryRangeKey,
  PopulationKey,
} from '@/lib/insights-history'

/**
 * Belonging — staying, coming back, and finding more than one home.
 *
 * Three behaviours that are related and not interchangeable, kept
 * apart everywhere on this page. A person can hold a membership for a
 * year without once opening it; another can leave a Collective and be
 * more present than ever in the one next door. Membership retention,
 * participation retention and cross-Collective belonging each get
 * their own section, and none of them is presented as the others.
 *
 * **These are not a measure of belonging.** Belonging is a feeling,
 * and what can be counted are behaviours that sometimes accompany it.
 * The page says so at the top rather than leaving the heading to imply
 * otherwise, and nothing here labels somebody disengaged for
 * participating less often than somebody else.
 */

const HISTORY_KEYS = [
  'unique_members',
  'memberships_started',
  'memberships_ended',
  'members_leaving_entirely',
  'memberships_rejoined',
  'returning_participants',
  'active_members',
  'members_in_one_collective',
  'members_in_two_collectives',
  'members_in_three_plus_collectives',
  'multi_collective_participants',
]

/** The cohort grid and the overlap comparison are point-in-time. */
const DETAIL_KEYS = [
  'membership_retention_cohorts',
  'overlap_vs_engagement',
  'multi_collective_members',
  'memberships_per_member',
  'participation_rate',
  'returning_participants',
]

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

export default function BelongingPage() {
  const [range, setRange] = useState<HistoryRangeKey>('last_12_months')
  const [grouping, setGrouping] = useState<Grouping>('monthly')
  const [population, setPopulation] = useState<PopulationKey>('production')
  const [period, setPeriod] = useState<PeriodKey>('this_month')

  const history = useHistory(HISTORY_KEYS, range, grouping, population)
  const { data: detail, error: detailError, loading } = useMetrics(
    DETAIL_KEYS, period, population,
  )
  // The cohort grid spans history rather than a period, so it is asked
  // for over all time regardless of the selector below.
  const { data: cohortData } = useMetrics(
    ['membership_retention_cohorts'], 'all_time', population,
  )

  return (
    <InsightsShell
      title="Belonging"
      intro="Whether people stay, come back, and find more than one home here."
    >
      <Caveat />

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
          title="Membership over time"
          explanation="How many people hold a membership at the end of each period. The line above the churn beneath it: this is the net result of everybody joining and everybody leaving."
          data={history.data}
          keys={['unique_members']}
          kind="line"
          hues={['teal']}
          footnote="A snapshot of people, counted once each however many Collectives they belong to — so it is the state at the close of each period and never a sum of its days."
        />

        <HistoryPanel
          title="Joining and leaving"
          explanation="Memberships that began and memberships that ended in each period. Counts memberships, not people: somebody leaving two Collectives is two endings."
          data={history.data}
          keys={['memberships_started', 'memberships_ended']}
          kind="column"
          hues={['teal', 'coral']}
          height={240}
          footnote="Endings rest on a recorded removal date. A membership marked as ended with no date cannot be placed in any period and is absent from all of them, so the endings line is a lower bound — the figure beneath the chart says how many such rows exist. Never read a short bar as proof that few people left."
        />
      </div>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Retention by joining month
        </h3>
        <p
          className="mb-4 mt-1 max-w-[76ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Of the people who joined in a given month, how many were still here
          later. Switch between the Collective they joined and Fresh
          Collective as a whole — the gap between the two is people who moved
          rather than left, which on a platform of many communities is the
          number that decides whether a departure matters.
        </p>
        <div
          className="rounded-2xl p-5 sm:p-6"
          style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
        >
          <Cohorts data={cohortData} />
        </div>
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Returning to participate
        </h3>
        <p
          className="mb-4 mt-1 max-w-[76ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Separate from membership retention, and deliberately so. Somebody
          who stays a member without attending a Gathering for a few weeks
          has not left anything — participation ebbs and flows, and nothing
          here treats a quiet stretch as a departure.
        </p>
        <div className="space-y-5">
          <HistoryPanel
            title="People taking part, and people coming back"
            explanation="Distinct participants in each period, beside those who had also taken part in the period before."
            data={history.data}
            keys={['active_members', 'returning_participants']}
            kind="column"
            hues={['teal', 'gold']}
            height={240}
            footnote="Returning is measured against the immediately preceding period of the same length, so the definition changes with the grouping — weekly means 'this week and last'. It is undefined over all time, which has no preceding period. A period where nobody was active before shows nobody returning, which is a true zero rather than a missing figure."
          />
        </div>
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Growing connections
        </h3>
        <p
          className="mb-4 mt-1 max-w-[76ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Whether people are finding the wider world here. Belonging to
          several Collectives and participating in several are different
          things, and both are below — somebody in three Collectives who only
          ever posts in one belongs to three and participates in one.
        </p>
        <div className="space-y-5">
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
            height={240}
            footnote="Worked out from membership join and removal dates rather than recorded at the time. A membership that ended before removal dates were stored is invisible here, which can place a member in a higher band than they belonged to on an early date."
          />
          <HistoryPanel
            title="People participating in more than one Collective"
            explanation="Distinct people who did something in two or more Collectives during each period — an act, not a membership."
            data={history.data}
            keys={['multi_collective_participants']}
            kind="column"
            hues={['teal']}
            footnote="Read against the bands above. Belonging to several and being active in several are different behaviours, and the gap between them is the ordinary fact that most people have a home Collective and visit the others."
          />
        </div>
        <div className="mt-5">
          <OverlapAndParticipation data={detail} />
        </div>
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Leaving and returning
        </h3>
        <p
          className="mb-4 mt-1 max-w-[76ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Who left Fresh Collective altogether rather than one of its
          Collectives, and who came back. Both rest on records with known
          limits, stated on each chart.
        </p>
        <div className="space-y-5">
          <HistoryPanel
            title="People leaving Fresh Collective"
            explanation="People who held a membership at the start of a period and none at the end. Leaving one Collective while remaining in another is not counted here."
            data={history.data}
            keys={['members_leaving_entirely']}
            kind="column"
            hues={['coral']}
            footnote="Rests on recorded removal dates, so a departure nobody dated is invisible and this is a lower bound. Compare it with the memberships-ended chart above: endings far exceeding departures is people moving between communities, which is the ecosystem working rather than failing."
          />
          <HistoryPanel
            title="Memberships rejoined"
            explanation="Memberships reactivated in each period, counted from the lifecycle event written at the time."
            data={history.data}
            keys={['memberships_rejoined']}
            kind="column"
            hues={['teal']}
            footnote="This one cannot be reconstructed. Rejoining used to overwrite the earlier membership, so the only evidence a rejoin happened is the event recorded at the time — and for periods before business-event recording began the chart shows a gap rather than a zero, because nobody wrote it down and that is not the same as nobody having rejoined."
          />
        </div>
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

        {detailError && <Problem message={detailError} />}
        {loading && !detail && <Waiting />}

        {detail && (
          <>
            <Band
              title="Staying and returning"
              note="Distinct people, counted once each."
            >
              <InsightCard
                metric={pick(detail, 'returning_participants')}
                hue="gold"
                caption="took part in this period and the one before"
              />
              <InsightCard
                metric={pick(detail, 'participation_rate')}
                hue="teal"
                caption="share of members taking part"
              />
            </Band>

            <Band
              title="More than one home"
              note="Membership overlap, which is not the same as participating in several."
            >
              <InsightCard
                metric={pick(detail, 'multi_collective_members')}
                hue="teal"
                caption="belong to more than one Collective"
              />
              <InsightCard
                metric={pick(detail, 'memberships_per_member')}
                hue="navy"
                caption="communities per person, on average"
              />
            </Band>
          </>
        )}
      </section>
    </InsightsShell>
  )
}

/**
 * Said before anything else on the page.
 *
 * The section is called Belonging and measures memberships and
 * actions, which are not the same thing. Leaving a heading to imply
 * that a participation count is a measure of how somebody feels would
 * be the most misleading thing on this dashboard, and it costs two
 * sentences to not do it.
 */
function Caveat() {
  return (
    <div
      className="mb-5 rounded-2xl p-5"
      style={{
        background: 'rgba(56, 160, 158, 0.06)',
        border: '1px solid rgba(56, 160, 158, 0.22)',
      }}
    >
      <p className="max-w-[80ch] text-[13px]" style={{ color: 'rgba(12, 24, 38, 0.78)' }}>
        Belonging is a feeling, and none of these figures measures it. What
        they count are behaviours that often sit alongside it — staying a
        member, coming back, finding a second community. Somebody quiet for a
        month has not stopped belonging, and nothing here should be read as
        saying they have.
      </p>
    </div>
  )
}

function Cohorts({ data }: { data: MetricResult | null }) {
  if (!data) {
    return (
      <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
        Building the cohorts…
      </p>
    )
  }
  const metric = pick(data, 'membership_retention_cohorts')
  if (!metric?.available) {
    return (
      <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
        {metric?.unavailable_reason ?? 'No cohorts available.'}
      </p>
    )
  }
  const rows = (metric.qualifiers?.cohorts ?? []) as CohortRow[]
  return (
    <CohortTable
      rows={rows}
      limitation={metric.qualifiers?.limitation as string | undefined}
      undated={metric.qualifiers?.undated_departures as number | undefined}
    />
  )
}

/**
 * Whether people in several Collectives take part more often.
 *
 * Presented as a description and never as a cause. People who join a
 * second Collective are plausibly the people who were already most
 * engaged, so the arrow could point either way — and the data here
 * cannot tell which. Read from the metric's own qualifiers rather than
 * recomputed.
 */
function OverlapAndParticipation({ data }: { data: MetricResult | null }) {
  const metric = data ? pick(data, 'overlap_vs_engagement') : null
  const buckets = metric?.qualifiers?.by_membership_count as
    | Record<string, { members: number; active: number; rate: number | null }>
    | undefined
  if (!metric?.available || !buckets) return null
  const rows = Object.entries(buckets).sort((a, b) => a[0].localeCompare(b[0]))
  if (rows.length === 0) return null

  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
    >
      <h4 className="font-serif text-[16px]" style={{ color: INK }}>
        Participation beside membership overlap
      </h4>
      <p className="mb-3 mt-1 max-w-[80ch] text-[12.5px]" style={{ color: INK_MUTED }}>
        The share of members who took part, grouped by how many Collectives
        they belong to.{' '}
        <strong style={{ color: INK }}>
          A description, not an explanation.
        </strong>{' '}
        People who join a second Collective are plausibly the people who were
        already the most engaged, so a higher rate here is as likely to be
        the cause of joining again as its result — these figures cannot tell
        which way the arrow points, and nothing on this page claims to.
      </p>
      <table className="w-full border-collapse text-left text-[12.5px]">
        <thead>
          <tr>
            {['Collectives', 'Members', 'Took part', 'Share'].map((h, i) => (
              <th
                key={h}
                scope="col"
                className={`border-b py-1.5 pr-3 font-semibold ${
                  i > 0 ? 'text-right' : ''
                }`}
                style={{ borderColor: '#E7EEF0', color: INK }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, b]) => (
            <tr key={label}>
              <th
                scope="row"
                className="border-b py-1.5 pr-3 font-normal"
                style={{ borderColor: '#E7EEF0', color: INK }}
              >
                {label}
              </th>
              <td
                className="border-b py-1.5 pr-3 text-right tabular-nums"
                style={{ borderColor: '#E7EEF0', color: INK_MUTED }}
              >
                {formatCount(b.members)}
              </td>
              <td
                className="border-b py-1.5 pr-3 text-right tabular-nums"
                style={{ borderColor: '#E7EEF0', color: INK_MUTED }}
              >
                {formatCount(b.active)}
              </td>
              <td
                className="border-b py-1.5 pr-3 text-right tabular-nums"
                style={{ borderColor: '#E7EEF0', color: INK }}
              >
                {b.rate === null ? '—' : `${Math.round(b.rate * 100)}%`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
