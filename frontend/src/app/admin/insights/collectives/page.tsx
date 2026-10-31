'use client'

import { useEffect, useState } from 'react'

import { CollectiveSelect } from '@/components/admin/insights/CollectiveSelect'
import { HistoryControls } from '@/components/admin/insights/HistoryControls'
import { HistoryPanel } from '@/components/admin/insights/HistoryPanel'
import { InsightCard } from '@/components/admin/insights/InsightCard'
import { InsightsShell } from '@/components/admin/insights/InsightsShell'
import { PeriodSelect } from '@/components/admin/insights/PeriodSelect'
import { StandingsTable } from '@/components/admin/insights/StandingsTable'
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
 * Collectives — how each community is faring, side by side.
 *
 * The page is a comparison rather than a total, which changes what the
 * charts mean: each line is a Collective and the metric is the axis.
 * Everywhere else on World Insights it is the other way round.
 *
 * Two things it deliberately does not do.
 *
 * **No blended score.** A single "engagement" number ranking
 * Collectives against each other would be a new definition invented
 * here, weighted by nothing in particular, and unarguable precisely
 * because nobody could say what it measured. The measures stay
 * separate and the reader does the combining.
 *
 * **No ranking a three-week-old Collective against a two-year-old
 * one.** Growth rankings require enough history, and the Collectives
 * that fall short are listed with the reason rather than dropped —
 * "new" and "not growing" look identical in a table that omits one of
 * them.
 */

/** Metrics compared per Collective. Six, at four Collectives, is the
 *  most the history endpoint will fan out in one request. */
const COMPARISON_KEYS = [
  'unique_members',
  'memberships_started',
  'participation_acts',
  'gathering_attendance',
  'pathway_steps_completed',
  'gross_collective_sales_cents',
]

/** Platform-level figures, which no Collective comparison can answer. */
const CARD_KEYS = [
  'total_collectives',
  'active_collectives',
  'draft_collectives',
  'archived_collectives',
  'multi_collective_members',
  'memberships_per_member',
  'engagement_by_theme',
]

const MAX_COMPARED = CHART_HUES.length
const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

export default function CollectivesPage() {
  const [range, setRange] = useState<HistoryRangeKey>('last_3_months')
  const [grouping, setGrouping] = useState<Grouping>('weekly')
  const [population, setPopulation] = useState<PopulationKey>('production')
  const [collectives, setCollectives] = useState<Collective[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [listError, setListError] = useState<string | null>(null)

  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const { data: cards, error: cardError, loading } = useMetrics(CARD_KEYS, period)

  // The selector follows the classification filter, so it can never
  // offer a Collective the charts would then exclude. Changing the
  // population re-picks the default selection rather than leaving a
  // stale one that returns nothing.
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

  const history = useHistory(
    COMPARISON_KEYS,
    range,
    grouping,
    population,
    selected,
  )
  const seriesFor = (key: string) =>
    (history.data?.series ?? []).filter((s) => s.key === key)

  return (
    <InsightsShell
      title="Collectives"
      intro="How each community is faring, which are attracting members, and how activity differs between them."
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

      <div className="mb-5">
        <CollectiveSelect
          collectives={collectives}
          selected={selected}
          onChange={setSelected}
          max={MAX_COMPARED}
          disabled={history.loading}
        />
      </div>

      {listError && <Problem message={listError} />}
      {history.error && <Problem message={history.error} />}

      {selected.length > 0 && (
        <>
          <div className="space-y-5">
            <HistoryPanel
              prominent
              title="Members, Collective by Collective"
              explanation="How many people hold a membership in each, at the end of each period. The shape of each line is the community's own story; the gaps between them are their relative size."
              data={history.data}
              keys={['unique_members']}
              collectiveIds={selected}
              kind="line"
              hues={[...CHART_HUES]}
              footnote="A snapshot per Collective — the figure at the close of the period, never a sum of its days. Somebody in two Collectives is counted once in each, so these lines do not add up to the platform total."
            />

            <HistoryPanel
              title="New memberships, Collective by Collective"
              explanation="Memberships that began in each period. Which communities are attracting people, as distinct from which are large."
              data={history.data}
              keys={['memberships_started']}
              collectiveIds={selected}
              kind="column"
              hues={[...CHART_HUES]}
              footnote="A flow, so each column is its own period's arrivals and the columns do add up over time."
            />
          </div>

          <section className="mt-12">
            <h3
              className="font-serif text-[17px] leading-tight"
              style={{ color: INK }}
            >
              Where the ranking stands
            </h3>
            <p
              className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
              style={{ color: INK_MUTED }}
            >
              Over the range selected above. Size and change are kept apart on
              purpose: a Collective can be the largest and the quietest at
              once, and one number covering both would say neither.
            </p>
            <div className="grid gap-4 lg:grid-cols-3">
              {(['size', 'growing', 'quietening'] as const).map((mode) => (
                <StandingsTable
                  key={mode}
                  series={seriesFor('unique_members')}
                  mode={mode}
                  unit="count"
                  metricName="Members"
                />
              ))}
            </div>
          </section>

          <section className="mt-12">
            <h3
              className="font-serif text-[17px] leading-tight"
              style={{ color: INK }}
            >
              Participation
            </h3>
            <p
              className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
              style={{ color: INK_MUTED }}
            >
              Three separate measures, deliberately not combined. A Collective
              built around Gatherings and one built around Pathways are both
              working; a single blended score would rank one above the other
              for being a different kind of community.
            </p>
            <div className="space-y-5">
              <HistoryPanel
                title="Acts of participation"
                explanation="Posts, comments, reactions, attendance and completed Pathway steps, counted together as acts rather than weighted into a score."
                data={history.data}
                keys={['participation_acts']}
                collectiveIds={selected}
                kind="column"
                hues={[...CHART_HUES]}
                footnote="Counts acts, not people — one very active member and ten occasional ones can produce the same figure. Read beside the member counts above."
              />
              <HistoryPanel
                title="Gathering attendance"
                explanation="Attendances recorded against Gatherings, dated by when the Gathering happened rather than when the register was marked."
                data={history.data}
                keys={['gathering_attendance']}
                collectiveIds={selected}
                kind="column"
                hues={[...CHART_HUES]}
              />
              <HistoryPanel
                title="Pathway steps completed"
                explanation="Steps members finished in each period."
                data={history.data}
                keys={['pathway_steps_completed']}
                collectiveIds={selected}
                kind="column"
                hues={[...CHART_HUES]}
              />
            </div>
          </section>

          <section className="mt-12">
            <h3
              className="font-serif text-[17px] leading-tight"
              style={{ color: INK }}
            >
              Sales
            </h3>
            <p
              className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
              style={{ color: INK_MUTED }}
            >
              Volume moved through each Collective. Not Fresh
              Collective&rsquo;s income — most of it belongs to the creator who
              earned it, and the Money page keeps that distinction.
            </p>
            <HistoryPanel
              title="Gross sales, Collective by Collective"
              explanation="Everything members paid, before any deduction, in each period."
              data={history.data}
              keys={['gross_collective_sales_cents']}
              collectiveIds={selected}
              kind="column"
              hues={[...CHART_HUES]}
              footnote="Attributed to the period the money arrived in. A Collective with no paid offerings shows nothing here, which is a fact about how it is run rather than a gap in the data."
            />
          </section>
        </>
      )}

      <section className="mt-12">
        <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>
          The figures behind them
        </h3>
        <p
          className="mb-4 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK_MUTED }}
        >
          Platform-level counts no single Collective can answer, with their own
          period below.
        </p>

        <div className="mb-6">
          <PeriodSelect value={period} onChange={setPeriod} disabled={loading} />
        </div>

        {cardError && <Problem message={cardError} />}
        {loading && !cards && <Waiting />}

        {cards && (
          <>
            <Band
              title="Collectives in existence"
              note="Observed on the day, never reconstructed — a Collective's status is stored as one value with no history behind it."
            >
              <InsightCard
                metric={pick(cards, 'total_collectives')}
                hue="navy"
                caption="all Collectives, at any stage"
              />
              <InsightCard
                metric={pick(cards, 'active_collectives')}
                hue="teal"
                caption="published and open"
              />
              <InsightCard
                metric={pick(cards, 'draft_collectives')}
                hue="navy"
                caption="still being built"
              />
              <InsightCard
                metric={pick(cards, 'archived_collectives')}
                hue="navy"
                caption="closed, and kept"
              />
            </Band>

            <Band
              title="Members across Collectives"
              note="Whether people are finding more than one community here. A platform question by nature — no single Collective can answer it."
            >
              <InsightCard
                metric={pick(cards, 'multi_collective_members')}
                hue="teal"
                caption="people in more than one Collective"
              />
              <InsightCard
                metric={pick(cards, 'memberships_per_member')}
                hue="navy"
                caption="communities per person, on average"
              />
            </Band>

            <ThemeBreakdown data={cards} />
          </>
        )}
      </section>
    </InsightsShell>
  )
}

/**
 * Which themes are finding people.
 *
 * Read from the metric's own qualifiers rather than recomputed here.
 * Themes are multi-select, so a Collective counts under each of its
 * themes and the bars sum to more than the platform total — said
 * plainly, because a reader who adds them up and gets too much will
 * assume the figures are wrong rather than that the question is.
 */
function ThemeBreakdown({ data }: { data: MetricResult }) {
  const metric = pick(data, 'engagement_by_theme')
  const breakdown = metric?.qualifiers?.active_members_by_theme as
    | Record<string, number>
    | undefined
  if (!metric) return null
  if (!breakdown || Object.keys(breakdown).length === 0) {
    return (
      <div
        className="rounded-2xl p-5"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
      >
        <h4 className="font-serif text-[16px]" style={{ color: INK }}>
          Themes
        </h4>
        <p className="mt-1 text-[12.5px]" style={{ color: INK_MUTED }}>
          {metric.available
            ? 'Nobody participated in the selected period, so there is nothing to attribute to a theme.'
            : (metric.unavailable_reason ?? 'No figures available.')}
        </p>
      </div>
    )
  }

  const rows = Object.entries(breakdown).sort((a, b) => b[1] - a[1])
  const top = rows[0][1] || 1

  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
    >
      <h4 className="font-serif text-[16px]" style={{ color: INK }}>
        Themes finding people
      </h4>
      <p className="mb-3 mt-1 max-w-[72ch] text-[12.5px]" style={{ color: INK_MUTED }}>
        Active members in the Collectives carrying each theme. Themes are
        multi-select, so a Collective counts under every theme it claims and
        these add up to more than the platform total.
      </p>
      <ul className="m-0 list-none space-y-1.5 p-0">
        {rows.map(([theme, count]) => (
          <li key={theme} className="flex items-center gap-3 text-[12.5px]">
            <span className="w-36 shrink-0" style={{ color: INK }}>
              {theme}
            </span>
            <span
              className="h-2 rounded-full"
              style={{
                width: `${Math.max(2, (count / top) * 100)}%`,
                maxWidth: '60%',
                background: '#22a598',
              }}
              aria-hidden="true"
            />
            <span className="tabular-nums" style={{ color: INK_MUTED }}>
              {formatCount(count)}
            </span>
          </li>
        ))}
      </ul>
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
