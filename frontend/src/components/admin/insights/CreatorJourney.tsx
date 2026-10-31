'use client'

import {
  type Creator,
  type StageCount,
  byOperator,
  formatExactValue,
  stageCounts,
} from '@/lib/insights-history'
import { formatCount } from '@/lib/insights'

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const RULE = '#E7EEF0'
const TEAL = '#22a598'

/**
 * Where each creator has got to, and where the drop-offs are.
 *
 * Two readings of the same people, side by side, because either alone
 * misleads. **Reached** only ever narrows and shows the shape of the
 * journey. **At** shows where people are standing now, and is the
 * number that answers "who has stopped" — a creator who built a
 * Collective in March and has done nothing since is invisible in the
 * first reading and obvious in the second.
 *
 * Deliberately not a score. A stage is the furthest point reached, so
 * a creator appears once; there is no weighting, no index, and no way
 * to rank a creator who started last week against one who started last
 * year, because the thing being shown is a position rather than a
 * performance.
 */
export function CreatorJourney({ creators }: { creators: Creator[] }) {
  const stages = stageCounts(creators)
  const total = stages[0]?.reached ?? 0

  return (
    <section
      className="rounded-2xl p-5 sm:p-6"
      style={{ background: '#FFFFFF', border: `1px solid ${RULE}` }}
    >
      <h3 className="font-serif text-[19px] leading-tight" style={{ color: INK }}>
        The creator journey
      </h3>
      <p className="mb-5 mt-1 max-w-[70ch] text-[13px]" style={{ color: INK_MUTED }}>
        How far each creator has got. Every stage implies the ones before
        it, so a creator stands at one point rather than being scored
        across several.
      </p>

      {total === 0 ? (
        <p className="py-6 text-[13px]" style={{ color: INK_MUTED }}>
          No creators in this classification.
        </p>
      ) : (
        <ol className="m-0 list-none space-y-3 p-0">
          {stages.map((s, i) => (
            <Stage
              key={s.key}
              stage={s}
              total={total}
              previous={i > 0 ? stages[i - 1] : null}
            />
          ))}
        </ol>
      )}
    </section>
  )
}

function Stage({
  stage,
  total,
  previous,
}: {
  stage: StageCount
  total: number
  previous: StageCount | null
}) {
  const width = total > 0 ? (stage.reached / total) * 100 : 0
  const lost = previous ? previous.reached - stage.reached : 0

  return (
    <li>
      <div className="flex items-baseline gap-2">
        <span className="text-[13px] font-semibold" style={{ color: INK }}>
          {stage.label}
        </span>
        <span className="text-[12px]" style={{ color: INK_MUTED }}>
          {stage.blurb}
        </span>
        <span className="ml-auto text-[13px] tabular-nums" style={{ color: INK }}>
          {formatCount(stage.reached)}
        </span>
      </div>
      <div
        className="mt-1 h-2.5 w-full overflow-hidden rounded-full"
        style={{ background: 'rgba(12, 24, 38, 0.05)' }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.max(width, 1)}%`, background: TEAL }}
          aria-hidden="true"
        />
      </div>
      <p className="mt-1 text-[11.5px]" style={{ color: INK_MUTED }}>
        {formatCount(stage.at)} stopped here
        {lost > 0 && (
          <>
            {' · '}
            {formatCount(lost)} did not go on from{' '}
            {previous?.label.toLowerCase()}
          </>
        )}
      </p>
    </li>
  )
}

/**
 * Every creator, with their stage — founder-operated kept apart from
 * independent.
 *
 * Separated rather than ranked together. Fresh Collective operating
 * its own Collectives and an external creator building one are not
 * two entries on the same leaderboard: the founder did not have to be
 * attracted to the platform, and a table that sorted them together
 * would make the one genuine external creator look like a poor
 * performer against two in-house communities.
 */
export function CreatorTable({ creators }: { creators: Creator[] }) {
  const { founder, independent } = byOperator(creators)
  return (
    <div className="space-y-5">
      <Group
        title="Independent creators"
        note="People who came to Fresh Collective and built something. The journey above is really about these."
        creators={independent}
        empty="No independent creators in this classification yet."
      />
      <Group
        title="Founder-operated"
        note="Collectives run by Fresh Collective itself. Real communities, but not evidence that the platform attracts creators — which is why they are counted separately rather than ranked alongside."
        creators={founder}
        empty="No founder-operated Collectives in this classification."
      />
    </div>
  )
}

function Group({
  title,
  note,
  creators,
  empty,
}: {
  title: string
  note: string
  creators: Creator[]
  empty: string
}) {
  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: '#FFFFFF', border: `1px solid ${RULE}` }}
    >
      <h4 className="font-serif text-[16px] leading-tight" style={{ color: INK }}>
        {title}
      </h4>
      <p className="mb-3 mt-1 max-w-[76ch] text-[12.5px]" style={{ color: INK_MUTED }}>
        {note}
      </p>
      {creators.length === 0 ? (
        <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
          {empty}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[12.5px]">
            <thead>
              <tr>
                {['Creator', 'Stage', 'Collectives', 'Members', 'Earned'].map(
                  (h, i) => (
                    <th
                      key={h}
                      scope="col"
                      className={`border-b py-1.5 pr-3 font-semibold ${
                        i >= 3 ? 'text-right' : ''
                      }`}
                      style={{ borderColor: RULE, color: INK }}
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {creators.map((c) => (
                <tr key={c.id}>
                  <th
                    scope="row"
                    className="border-b py-1.5 pr-3 font-normal"
                    style={{ borderColor: RULE, color: INK }}
                  >
                    {c.name}
                    {c.reporting_class &&
                      c.reporting_class !== 'production' && (
                        <span className="ml-1.5" style={{ color: INK_MUTED }}>
                          {c.reporting_class}
                        </span>
                      )}
                  </th>
                  <td
                    className="border-b py-1.5 pr-3"
                    style={{ borderColor: RULE, color: INK_MUTED }}
                  >
                    {c.stage}
                  </td>
                  <td
                    className="border-b py-1.5 pr-3"
                    style={{ borderColor: RULE, color: INK_MUTED }}
                  >
                    {c.collectives.length > 0 ? c.collectives.join(', ') : '—'}
                  </td>
                  <td
                    className="border-b py-1.5 pr-3 text-right tabular-nums"
                    style={{ borderColor: RULE, color: INK_MUTED }}
                  >
                    {formatCount(c.members)}
                  </td>
                  <td
                    className="border-b py-1.5 pr-3 text-right tabular-nums"
                    style={{ borderColor: RULE, color: INK_MUTED }}
                  >
                    {formatExactValue('money_cents', c.earned_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
