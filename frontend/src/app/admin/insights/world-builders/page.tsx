'use client'

import { useEffect, useState } from 'react'

import { HistoryControls } from '@/components/admin/insights/HistoryControls'
import { HistoryPanel } from '@/components/admin/insights/HistoryPanel'
import { CardNote, InsightCard } from '@/components/admin/insights/InsightCard'
import {
  CardGroup,
  CardSurfaceScope,
  InsightsSection,
  PanelGroup,
} from '@/components/admin/insights/InsightsSection'
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
  fetchCollectives,
} from '@/lib/insights-history'
import { CARD, INK as FC_INK, STATUS, surfaceForGroup } from '@/lib/insights-palette'

/**
 * World Builders — the creator learning environment, measured.
 *
 * Its own tab rather than a section of Creators, because its
 * classification is the reason it was invisible. World Builders is
 * ``internal_operations`` and stays that way: every Production figure
 * on the other six dashboards continues to exclude it, which is
 * correct — creators learning to build is not trade with members. A
 * dashboard that fixed the visibility by reclassifying it would have
 * quietly corrupted the other six.
 *
 * Almost nothing here is a new measure. The reporting API already
 * answers thirty-two metrics per Collective, so membership,
 * participation, Pathway steps, Gatherings and Conversations are the
 * existing metrics with a Collective filter. Three questions needed
 * new metrics and they live in ``app/reporting/world_builders.py``.
 *
 * The one thing this page refuses to do
 * -------------------------------------
 * It does not present a Joined stage. Membership is granted
 * automatically to every eligible creator, so "creators who joined"
 * would describe a decision nobody made. The honest shape is
 * **Eligible → Took part → Came back**, and the gap between eligible
 * and member is reported as a reconciliation fact rather than as a
 * funnel step.
 */

/** Scoped to World Builders, via the Collective filter on /query. */
const SCOPED_KEYS = [
  'unique_members',
  'active_members',
  'participation_acts',
  'participation_rate',
  'returning_participants',
  'pathway_participants',
  'pathway_steps_completed',
  'gathering_attendees',
  'gathering_bookings',
  'repeat_gathering_attendees',
  'conversation_contributors',
]

/** Platform-level, and meaningless narrowed to one Collective. */
const PLATFORM_KEYS = [
  'wb_eligible_creators',
  'wb_creator_participation',
  'wb_creator_development',
]

const SCOPED_HISTORY = [
  'unique_members',
  'active_members',
  'participation_acts',
  'returning_participants',
  'pathway_participants',
  'pathway_steps_completed',
  'gathering_attendees',
  'conversation_contributors',
]

const INK_MUTED = FC_INK.muted

/**
 * Find World Builders by its rule, never by its name.
 *
 * ``learning_environment`` is the API's word for
 * ``spaces.auto_grant_role IS NOT NULL`` — the same structural lookup
 * the eligibility reconciler and the Creator Studio handoff use. A
 * page matching on the string "World Builders" would break the day it
 * is renamed and would pick up any Collective that shared the name.
 */
function useLearningCollective() {
  const [state, setState] = useState<{
    collective: Collective | null
    error: string | null
    loading: boolean
  }>({ collective: null, error: null, loading: true })

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    fetchCollectives('all', controller.signal)
      .then((rows) => {
        if (cancelled) return
        const found = rows.find((c) => c.learning_environment) ?? null
        setState({ collective: found, error: null, loading: false })
      })
      .catch((e: Error) => {
        if (cancelled || e.name === 'AbortError') return
        setState({ collective: null, error: e.message, loading: false })
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [])

  return state
}

export default function WorldBuildersPage() {
  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const [range, setRange] = useState<HistoryRangeKey>('last_3_months')
  const [grouping, setGrouping] = useState<Grouping>('weekly')

  const { collective, error: findError, loading: finding } =
    useLearningCollective()
  const ids = collective ? [collective.id] : []

  // Everything here is deliberately unfiltered by reporting class.
  // World Builders is internal_operations, so a Production filter
  // would empty its own dashboard — the classification is preserved
  // by the other six pages honouring it, not by this one repeating it.
  const scoped = useMetrics(SCOPED_KEYS, period, 'all', ids)
  const platform = useMetrics(PLATFORM_KEYS, period, 'all')
  const history = useHistory(SCOPED_HISTORY, range, grouping, 'all', ids)

  return (
    <InsightsShell
      title="World Builders"
      intro="The creator learning environment: who it reaches, what they use, and whether they come back."
    >
      <Explainer />

      {findError && <Problem message={findError} />}
      {!finding && !collective && <NotFound />}

      {collective && (
        <>
          <HistoryControls
            range={range}
            grouping={grouping}
            population="all"
            onRange={setRange}
            onGrouping={setGrouping}
            options={history.data?.options}
            disabled={history.loading}
          />

          {history.error && <Problem message={history.error} />}

          <InsightsSection
            lead
            title="Creator reach"
            intro="How many creators World Builders holds, and how many of them did something in each period."
          >
            <PanelGroup>
              <HistoryPanel
                prominent
                title="Creators here, and creators taking part"
                explanation="Everyone with access, against the smaller number who did something in the period."
                data={history.data}
                keys={['unique_members', 'active_members']}
                kind="line"
                hues={['navy', 'teal']}
                footnote="Access is granted automatically to every eligible creator, so the upper line is reach rather than a count of people who chose to join. The gap between the two lines is the thing worth watching."
              />

              <HistoryPanel
                title="Coming back"
                explanation="Creators who took part in this period and had also taken part before."
                data={history.data}
                keys={['returning_participants']}
                kind="column"
                hues={['teal']}
                footnote="Somebody who stops appearing has not necessarily disengaged. They may have found the guidance they came for, which is the point of a learning environment."
              />
            </PanelGroup>
          </InsightsSection>

          <InsightsSection
            title="Learning and exploration"
            intro="Which parts of World Builders creators actually use."
          >
            <PanelGroup>
              <HistoryPanel
                title="Pathway steps completed"
                explanation="Steps finished inside World Builders Pathways."
                data={history.data}
                keys={['pathway_steps_completed']}
                kind="column"
                hues={['navy']}
                footnote="Steps, never Pathways. No reliable completion event is recorded, so nothing here says a creator finished a Pathway — see the note at the foot of this page."
              />

              <HistoryPanel
                title="Creators in Pathways"
                explanation="People who completed at least one step in the period, counted once each."
                data={history.data}
                keys={['pathway_participants']}
                kind="column"
                hues={['teal']}
                footnote="Distinct people rather than steps, so one creator working through twelve steps is one participant."
              />

              <HistoryPanel
                title="Gatherings and Conversations"
                explanation="Creators who attended a Gathering, and creators who posted, commented or reacted."
                data={history.data}
                keys={['gathering_attendees', 'conversation_contributors']}
                kind="line"
                hues={['gold', 'watermelon']}
                footnote="Attendance is recorded by a creator marking the register, so a Gathering nobody marked reads as unattended rather than as missing. Conversation activity counts that an act happened and never reads what it said."
              />
            </PanelGroup>
          </InsightsSection>

          <InsightsSection
            title="The figures behind them"
            intro={
              <>
                These have their own period, chosen below and independent
                of the charts above.
              </>
            }
          >
            <div className="mb-6">
              <PeriodSelect
                value={period}
                onChange={setPeriod}
                disabled={scoped.loading}
              />
            </div>

            {scoped.error && <Problem message={scoped.error} />}
            {platform.error && <Problem message={platform.error} />}
            {scoped.loading && !scoped.data && <Waiting />}

            {platform.data && (
              <CardGroup surface={surfaceForGroup(0)}
                title="Reach"
                note="Eligibility is a platform figure; the rest describe World Builders itself."
              >
                <InsightCard
                  metric={pick(platform.data, 'wb_eligible_creators')}
                  hue="navy"
                  caption="creators the automatic-access rule covers"
                />
                {scoped.data && (
                  <InsightCard
                    metric={pick(scoped.data, 'unique_members')}
                    hue="navy"
                    caption="creators holding membership here"
                  />
                )}
                <InsightCard
                  metric={pick(platform.data, 'wb_creator_participation')}
                  hue="teal"
                  caption="creators who did something in the period"
                />
                <EligibilityNote data={platform.data} />
              </CardGroup>
            )}

            {scoped.data && (
              <>
                <CardGroup surface={surfaceForGroup(1)}
                  title="What they did"
                  note="Activity inside World Builders over the selected period."
                >
                  <InsightCard
                    metric={pick(scoped.data, 'participation_acts')}
                    hue="teal"
                    caption="posts, comments, reactions, attendances and steps"
                  />
                  <InsightCard
                    metric={pick(scoped.data, 'participation_rate')}
                    hue="teal"
                    caption="share of members taking part"
                  />
                  <InsightCard
                    metric={pick(scoped.data, 'pathway_steps_completed')}
                    hue="navy"
                    caption="Pathway steps finished"
                  />
                  <InsightCard
                    metric={pick(scoped.data, 'pathway_participants')}
                    hue="navy"
                    caption="people who finished at least one step"
                  />
                </CardGroup>

                <CardGroup surface={surfaceForGroup(2)}
                  title="Gatherings and Conversations"
                  note="Booking is an intention; attendance is a record somebody marked."
                >
                  <InsightCard
                    metric={pick(scoped.data, 'gathering_bookings')}
                    hue="gold"
                    caption="places booked"
                  />
                  <InsightCard
                    metric={pick(scoped.data, 'gathering_attendees')}
                    hue="gold"
                    caption="people recorded as attending"
                  />
                  <InsightCard
                    metric={pick(scoped.data, 'repeat_gathering_attendees')}
                    hue="gold"
                    caption="attended more than one"
                  />
                  <InsightCard
                    metric={pick(scoped.data, 'conversation_contributors')}
                    hue="watermelon"
                    caption="people who posted, commented or reacted"
                  />
                </CardGroup>
              </>
            )}

            <CardSurfaceScope surface={surfaceForGroup(3)}>
              {platform.data && <Development data={platform.data} />}
            </CardSurfaceScope>

            <CardSurfaceScope surface={surfaceForGroup(4)}>
              <NotMeasured />
            </CardSurfaceScope>
          </InsightsSection>
        </>
      )}
    </InsightsShell>
  )
}

/**
 * What World Builders is, said once at the top.
 *
 * On a page of figures about a Collective that does not appear in any
 * Production total, the first question is why — so it is answered
 * before the first number rather than in a footnote.
 */
function Explainer() {
  return (
    <div
      className="mb-6 rounded-2xl p-5"
      style={{
        background: 'rgba(56, 160, 158, 0.06)',
        border: '1px solid rgba(56, 160, 158, 0.22)',
      }}
    >
      <p className="max-w-[80ch] text-[13px]" style={{ color: 'rgba(12, 24, 38, 0.82)' }}>
        World Builders is where creators learn to build — establishing a
        Collective, making Pathways, running Gatherings, developing
        Offerings. It is classified <strong>internal operations</strong>,
        so none of this activity appears in the Production figures on the
        other six dashboards. That is deliberate: creators learning is
        not trade with members, and folding it in would overstate both.
      </p>
    </div>
  )
}

/**
 * The eligible-versus-member gap, in both directions.
 *
 * Neither direction is an error, and both are easy to misread as one.
 */
function EligibilityNote({ data }: { data: MetricResult }) {
  const metric = pick(data, 'wb_eligible_creators')
  const q = metric?.qualifiers ?? {}
  const without = q.eligible_without_membership
  const notEligible = q.members_not_eligible
  if (typeof without !== 'number' || typeof notEligible !== 'number') return null

  return (
    <CardNote accent="teal">
      <p className="text-[13px]" style={{ color: CARD.ink }}>
        Access is granted automatically, so joining is not a step a
        creator takes.
      </p>
      <p className="mt-2 text-[12.5px]" style={{ color: CARD.ink }}>
        {formatCount(without)} eligible{' '}
        {without === 1 ? 'creator holds' : 'creators hold'} no membership row
        yet, and {formatCount(notEligible)}{' '}
        {notEligible === 1 ? 'member is' : 'members are'} not eligible — an
        account operating a Collective from an admin role is a member here
        and is not covered by the rule.
      </p>
    </CardNote>
  )
}

/**
 * Where creators have got to, beside whether they used World Builders.
 *
 * Two columns, described and never explained. Creators who seek out
 * guidance are not a random sample of creators, so a difference
 * between the columns is not evidence that World Builders produced it
 * — and the note under the table says exactly that rather than
 * leaving the reader to supply the causal story themselves.
 */
function Development({ data }: { data: MetricResult }) {
  const metric = pick(data, 'wb_creator_development')
  const q = metric?.qualifiers ?? {}
  const took = q.participated as Record<string, number> | undefined
  const didnt = q.did_not_participate as Record<string, number> | undefined
  if (!took || !didnt) return null

  const rows: [string, keyof typeof took][] = [
    ['Creators', 'creators'],
    ['Have a Collective', 'has_collective'],
    ['Have a first member', 'has_member'],
    ['Have a first sale', 'has_sale'],
  ]

  return (
    <section className="mb-8">
      <h3
        className="font-serif text-[15.5px] leading-tight"
        style={{ color: '#0C1826' }}
      >
        Creator development
      </h3>
      <p
        className="mb-3 mt-1 max-w-[72ch] text-[12.5px]"
        style={{ color: INK_MUTED }}
      >
        How far creators have got, beside whether they have ever taken part
        in World Builders. A current state, not a trend.
      </p>
      <CardNote>
        <div className="max-w-full overflow-x-auto">
          <table className="w-full min-w-[420px] border-collapse text-[13px]">
            <thead>
              <tr>
                <th className="py-1.5 text-left font-semibold" style={{ color: CARD.ink }}>
                  &nbsp;
                </th>
                <th className="py-1.5 pl-4 text-right font-semibold" style={{ color: CARD.ink }}>
                  Took part
                </th>
                <th className="py-1.5 pl-4 text-right font-semibold" style={{ color: CARD.ink }}>
                  Did not
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, key]) => (
                <tr key={key}>
                  <td className="py-1.5" style={{ color: CARD.ink }}>
                    {label}
                  </td>
                  <td
                    className="py-1.5 pl-4 text-right tabular-nums"
                    style={{ color: CARD.ink }}
                  >
                    {formatCount(took[key] ?? 0)}
                  </td>
                  <td
                    className="py-1.5 pl-4 text-right tabular-nums"
                    style={{ color: CARD.ink }}
                  >
                    {formatCount(didnt[key] ?? 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 max-w-[80ch] text-[12.5px]" style={{ color: CARD.ink }}>
          Descriptive only. Creators who come looking for guidance are not
          a random sample of creators — somebody already building is more
          likely to arrive here — so a difference between these columns is
          not evidence that World Builders caused it.
        </p>
      </CardNote>
    </section>
  )
}

/**
 * The measures that were asked for and are not here.
 *
 * Listed on the page rather than left as an absence, because a missing
 * tile reads as "nothing happened" and these are all "this is not
 * recorded".
 */
function NotMeasured() {
  const gaps: [string, string][] = [
    [
      'Pathway completion',
      'No completion event is emitted, and a step count cannot stand in for one — the steps in a Pathway change over time, so "finished every step" has no answer for a past date.',
    ],
    [
      'Resource and Offering use',
      'Entitlements record who was granted access to a download. Nothing records a view or a download, so there is no honest usage figure to show.',
    ],
    [
      'First Pathway or Gathering published',
      'A Pathway carries a status and no publication date, and a Gathering carries a published flag and no date, so neither milestone can be dated — even for today.',
    ],
  ]

  return (
    <section className="mb-2">
      <h3
        className="font-serif text-[15.5px] leading-tight"
        style={{ color: '#0C1826' }}
      >
        What is not measured yet
      </h3>
      <p
        className="mb-3 mt-1 max-w-[72ch] text-[12.5px]"
        style={{ color: INK_MUTED }}
      >
        Asked for, and absent because the records do not support them. An
        estimate here would be worse than a gap.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        {gaps.map(([title, why]) => (
          <CardNote key={title} accent="gold">
            <h4
              className="text-[13.5px] font-semibold leading-snug"
              style={{ color: CARD.ink }}
            >
              {title}
            </h4>
            <p className="mt-2 text-[12.5px]" style={{ color: CARD.ink }}>
              {why}
            </p>
          </CardNote>
        ))}
      </div>
    </section>
  )
}


function NotFound() {
  return (
    <div
      className="mb-5 rounded-2xl p-5"
      style={{
        background: STATUS.warning.bg,
        border: `1px solid ${STATUS.warning.border}`,
      }}
    >
      <p className="text-[13.5px]" style={{ color: STATUS.warning.fg }}>
        No Collective grants membership automatically by role, so there is
        no learning environment to report on. This page finds World
        Builders by that rule rather than by name.
      </p>
    </div>
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
