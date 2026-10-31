'use client'

import { useEffect, useState } from 'react'

import { CollectiveSelect } from '@/components/admin/insights/CollectiveSelect'
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
import {
  type Collective,
  type Grouping,
  type HistoryRangeKey,
  type PopulationKey,
  CHART_HUES,
  fetchCollectives,
} from '@/lib/insights-history'

/**
 * Participation — whether people are doing anything, and what.
 *
 * The page is built on one distinction and repeats it everywhere:
 * **people are not acts**. One member at three Gatherings is three
 * attendances and one person, and every chart here says which of the
 * two it is counting. Membership is not participation either — joining
 * and turning up are different facts, and the rate between them is the
 * question worth asking.
 *
 * No blended engagement score, as on Collectives and for the same
 * reason: a community built around Gatherings and one built around
 * Pathways are both working, and a weighted total would rank one above
 * the other for being a different kind of place. The activity types
 * stay in separate charts.
 *
 * **What is deliberately absent.** Pathway completion.
 * ``ActivityType.pathway_completed`` exists in the model and nothing in
 * the application emits it, and a Pathway has no stored step count with
 * history — so neither a completion nor a completion rate can be
 * computed for a past date without inventing one. Steps completed and
 * people progressing are reported instead, and they are what the
 * records actually support.
 */

const PLATFORM_KEYS = [
  'active_members',
  'participation_acts',
  'participation_rate',
  'returning_participants',
  'gathering_bookings',
  'gathering_attendance',
  'gathering_attendees',
  'pathway_steps_completed',
  'pathway_participants',
  'conversation_contributors',
]

/** Compared per Collective. Kept small — four Collectives multiplies it. */
const COMPARISON_KEYS = [
  'active_members',
  'participation_acts',
  'gathering_attendance',
  'pathway_steps_completed',
]

const CARD_KEYS = [
  'active_members',
  'unique_members',
  'participation_rate',
  'participation_acts',
  'returning_participants',
  'repeat_gathering_attendees',
  'gathering_attendees',
  'conversation_contributors',
]

const MAX_COMPARED = CHART_HUES.length
const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

export default function ParticipationPage() {
  const [range, setRange] = useState<HistoryRangeKey>('last_3_months')
  const [grouping, setGrouping] = useState<Grouping>('weekly')
  const [population, setPopulation] = useState<PopulationKey>('production')
  const [collectives, setCollectives] = useState<Collective[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [listError, setListError] = useState<string | null>(null)

  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const { data: cards, error: cardError, loading } = useMetrics(
    CARD_KEYS, period, population,
  )

  const history = useHistory(PLATFORM_KEYS, range, grouping, population)
  const comparison = useHistory(
    COMPARISON_KEYS, range, grouping, population, selected,
  )

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    fetchCollectives(population, controller.signal)
      .then((rows) => {
        if (cancelled) return
        setCollectives(rows)
        setListError(null)
        setSelected(
          rows
            .filter((c) => c.history_begins !== null)
            .slice(0, MAX_COMPARED)
            .map((c) => c.id),
        )
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
      title="Participation"
      intro="Whether people are taking part, how they take part, and whether they come back."
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

      {history.error && <Problem message={history.error} />}

      <div className="space-y-5">
        <HistoryPanel
          prominent
          title="People taking part"
          explanation="Distinct people who did something in each period — posted, commented, reacted, attended a Gathering, completed a Pathway step or bought something. Somebody who did all six is one person here."
          data={history.data}
          keys={['active_members']}
          kind="line"
          hues={['teal']}
          footnote="A distinct count, so it is recomputed for whatever period you ask for and never summed from shorter ones — thirty daily figures do not make a monthly one, because the same person appears on many days. Only activity the platform records counts: somebody who read everything and posted nothing is not here, which is a limit of what can be observed rather than a judgement about them."
        />

        <HistoryPanel
          title="Acts of participation"
          explanation="How much happened, as distinct from how many people made it happen. Read beside the chart above: the two rising together is a community growing, one rising alone is the same people doing more — or fewer people doing much more."
          data={history.data}
          keys={['participation_acts']}
          kind="column"
          hues={['navy']}
          footnote="An additive flow, so these columns do add up over time — unlike the people count above, which cannot be added."
        />

        <HistoryPanel
          title="Coming back"
          explanation="People who took part in a period and had also taken part in the one before it. The signal membership counts cannot give: whether participation is a habit or a single visit."
          data={history.data}
          keys={['returning_participants']}
          kind="column"
          hues={['gold']}
          footnote="Returning is defined against the immediately preceding period of the same length, so the definition changes with the grouping: weekly means 'active this week and last', monthly means 'this month and last'. It is undefined over all time, which has no preceding period, and the first period of any range has nothing before it to compare with."
        />
      </div>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Gatherings
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Booking and attending are different facts, and the gap between
          them is partly people who did not come and partly registers
          nobody marked. Attendance below is recorded attendance only —
          never assumed from a booking.
        </p>
        <HistoryPanel
          title="Booked and attended"
          explanation="Places booked on Gatherings held in each period, beside attendances actually recorded against them."
          data={history.data}
          keys={['gathering_bookings', 'gathering_attendance']}
          kind="column"
          hues={['navy', 'teal']}
          height={240}
          footnote="Both are dated by when the Gathering happened rather than when the booking was made, so a September booking for an October Gathering counts in October on both lines — otherwise the pair could not be compared. A Gathering whose register was never marked contributes bookings and no attendance, so the attended figure is a lower bound: it understates attendance and never overstates it."
        />
        <div className="mt-5">
          <HistoryPanel
            title="People attending"
            explanation="Distinct people at Gatherings in each period, as against the number of attendances above."
            data={history.data}
            keys={['gathering_attendees']}
            kind="column"
            hues={['teal']}
          />
        </div>
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Pathways
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Steps completed and the people completing them, on their own
          axes. Two charts rather than one: steps outnumber people several
          times over, so a shared axis flattened the people series into
          the baseline — and a second y-axis would have been worse, because
          two scales on one frame can be drawn to show any relationship you
          like. Read them together; the pairing is the point.
        </p>
        <div className="space-y-5">
          <HistoryPanel
            title="People progressing through Pathways"
            explanation="Distinct people who completed at least one Pathway step in each period. Somebody who finished nine steps is one person here."
            data={history.data}
            keys={['pathway_participants']}
            kind="column"
            hues={['teal']}
            footnote="A distinct count, so it is recomputed for whatever period and grouping you ask for and never summed from shorter ones — the same person appears in many days, and adding the days would count them many times."
          />
          <HistoryPanel
            title="Pathway steps completed"
            explanation="Total steps finished in each period, whoever finished them."
            data={history.data}
            keys={['pathway_steps_completed']}
            kind="column"
            hues={['navy']}
            footnote="An additive flow, so these columns do add up over time. Read against the chart above: steps rising while people stay flat is a few members working through a Pathway quickly, which is a different thing from many members starting one. Pathway completion is deliberately absent from both — nothing in the application records a completion, and a Pathway's step count is derived from its current steps with no history, so whether somebody finished a Pathway as it stood last March cannot be established. A completion rate from today's step count would be an estimate presented as a measurement."
          />
        </div>
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Conversations
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Whether people are talking to each other. Counts only —
          Fresh Collective&rsquo;s reporting never reads what anybody wrote,
          and no metric here touches a post body, a comment, a reflection or
          a direct message.
        </p>
        <HistoryPanel
          title="People contributing"
          explanation="Distinct people who posted, commented or reacted in each period."
          data={history.data}
          keys={['conversation_contributors']}
          kind="column"
          hues={['teal']}
          footnote="A reaction counts as contributing. That is deliberate — a member who reacts but never writes is still present in the conversation, and a measure that only counted authors would call the quieter half of a community absent."
        />
        <div className="mt-5">
          <ActivityMix data={cards} />
        </div>
      </section>

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          Collective by Collective
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Each activity type separately, never combined into a score. A
          Collective built around Gatherings and one built around Pathways
          are both working; a single number would rank one above the other
          for being a different kind of place.
        </p>

        <div className="mb-5">
          <CollectiveSelect
            collectives={collectives}
            selected={selected}
            onChange={setSelected}
            max={MAX_COMPARED}
            disabled={comparison.loading}
          />
        </div>

        {listError && <Problem message={listError} />}
        {comparison.error && <Problem message={comparison.error} />}

        {selected.length > 0 && (
          <div className="space-y-5">
            <HistoryPanel
              title="People taking part, by Collective"
              explanation="Distinct participants in each community."
              data={comparison.data}
              keys={['active_members']}
              collectiveIds={selected}
              kind="line"
              hues={[...CHART_HUES]}
              height={240}
              footnote="Somebody active in two of these is counted once in each, so the lines do not add up to the platform figure above."
            />
            <HistoryPanel
              title="Gathering attendance, by Collective"
              explanation="Recorded attendances in each community."
              data={comparison.data}
              keys={['gathering_attendance']}
              collectiveIds={selected}
              kind="column"
              hues={[...CHART_HUES]}
            />
            <HistoryPanel
              title="Pathway steps, by Collective"
              explanation="Steps completed in each community."
              data={comparison.data}
              keys={['pathway_steps_completed']}
              collectiveIds={selected}
              kind="column"
              hues={[...CHART_HUES]}
            />
          </div>
        )}
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

        {cards && (
          <>
            <Band
              title="People"
              note="Distinct people, counted once each however much they did."
            >
              <InsightCard
                metric={pick(cards, 'active_members')}
                hue="teal"
                caption="took part in the period"
              />
              <InsightCard
                metric={pick(cards, 'unique_members')}
                hue="navy"
                caption="members, whether they took part or not"
              />
              <InsightCard
                metric={pick(cards, 'participation_rate')}
                hue="teal"
                caption="share of members taking part"
              />
              <InsightCard
                metric={pick(cards, 'returning_participants')}
                hue="gold"
                caption="also took part in the previous period"
              />
            </Band>

            <Band
              title="Activity"
              note="How much happened. These count acts, not people — the band above counts people."
            >
              <InsightCard
                metric={pick(cards, 'participation_acts')}
                hue="navy"
                caption="acts of participation in the period"
              />
              <InsightCard
                metric={pick(cards, 'gathering_attendees')}
                hue="teal"
                caption="people at Gatherings"
              />
              <InsightCard
                metric={pick(cards, 'repeat_gathering_attendees')}
                hue="teal"
                caption="at more than one Gathering"
              />
              <InsightCard
                metric={pick(cards, 'conversation_contributors')}
                hue="navy"
                caption="people contributing to Conversations"
              />
            </Band>
          </>
        )}
      </section>
    </InsightsShell>
  )
}

/**
 * Which kinds of thing people are doing.
 *
 * Read from the act count's own ``by_kind`` qualifier rather than
 * recomputed, so the parts cannot disagree with the whole. Shown as a
 * share of acts and labelled as such: these are things that happened,
 * not people who did them, and the two are different everywhere else
 * on this page too.
 */
function ActivityMix({ data }: { data: MetricResult | null }) {
  const metric = data ? pick(data, 'participation_acts') : null
  const byKind = metric?.qualifiers?.by_kind as
    | Record<string, number>
    | undefined
  if (!metric?.available || !byKind) return null

  const rows = Object.entries(byKind)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
  if (rows.length === 0) return null
  const total = rows.reduce((n, [, v]) => n + v, 0)

  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
    >
      <h4 className="font-serif text-[16px]" style={{ color: INK }}>
        How people are taking part
      </h4>
      <p className="mb-3 mt-1 max-w-[76ch] text-[12.5px]" style={{ color: INK_MUTED }}>
        The mix of activity in the period selected at the foot of this page.
        These are <strong style={{ color: INK }}>acts</strong>, not people —
        one member at three Gatherings contributes three.
      </p>
      <ul className="m-0 list-none space-y-1.5 p-0">
        {rows.map(([kind, count]) => (
          <li key={kind} className="flex items-center gap-3 text-[12.5px]">
            <span className="w-44 shrink-0" style={{ color: INK }}>
              {KIND_LABELS[kind] ?? kind}
            </span>
            <span
              className="h-2 rounded-full"
              style={{
                width: `${Math.max(2, (count / rows[0][1]) * 100)}%`,
                maxWidth: '55%',
                background: '#22a598',
              }}
              aria-hidden="true"
            />
            <span className="tabular-nums" style={{ color: INK_MUTED }}>
              {formatCount(count)}
              <span className="ml-1.5 opacity-70">
                {Math.round((count / total) * 100)}%
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const KIND_LABELS: Record<string, string> = {
  conversation_post: 'Conversation posts',
  conversation_comment: 'Comments and replies',
  conversation_reaction: 'Reactions',
  gathering_attendance: 'Gathering attendance',
  pathway_step: 'Pathway steps',
  purchase: 'Purchases',
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
