'use client'

/**
 * CaretakerOverview — a compact row of pills that helps a caretaker
 * notice what may need their attention. Each pill acts as a filter or
 * navigation into the shared feed; nothing here is a metric to
 * optimise. If a count is 0 (or unavailable), its pill is omitted so
 * the row stays quiet by default.
 *
 * Explicitly avoided: engagement scores, response-time targets,
 * leaderboards, ranks, competitive analytics. This is a care surface,
 * not a dashboard.
 *
 * "Mentions" is not shown yet because we can't scope the current
 * notifications API cleanly per-collective — omitting rather than
 * inventing.
 */

interface Props {
  unansweredCount: number
  scheduledCount: number
  publishingTodayCount: number
  onOpenUnanswered: () => void
  onOpenQueue: () => void
  onOpenPublishingToday: () => void
}

export default function CaretakerOverview({
  unansweredCount, scheduledCount, publishingTodayCount,
  onOpenUnanswered, onOpenQueue, onOpenPublishingToday,
}: Props) {
  const items: {
    key: string
    label: string
    count: number
    countLabel: string
    onClick: () => void
  }[] = []

  if (unansweredCount > 0) {
    items.push({
      key: 'unanswered',
      label: 'Unanswered questions',
      count: unansweredCount,
      countLabel: unansweredCount === 1 ? '1 waiting' : `${unansweredCount} waiting`,
      onClick: onOpenUnanswered,
    })
  }
  if (scheduledCount > 0) {
    items.push({
      key: 'queue',
      label: 'In the queue',
      count: scheduledCount,
      countLabel: scheduledCount === 1 ? '1 conversation' : `${scheduledCount} conversations`,
      onClick: onOpenQueue,
    })
  }
  if (publishingTodayCount > 0) {
    items.push({
      key: 'today',
      label: 'Publishing today',
      count: publishingTodayCount,
      countLabel: publishingTodayCount === 1 ? '1 conversation' : `${publishingTodayCount} conversations`,
      onClick: onOpenPublishingToday,
    })
  }

  // Whole section disappears when nothing needs care — no "0" surface.
  if (items.length === 0) return null

  return (
    <section className="mb-5">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
        Care for your space
      </p>
      <div className="flex flex-wrap gap-2">
        {items.map((it) => (
          <button
            key={it.key}
            type="button"
            onClick={it.onClick}
            className="group flex items-center gap-2 rounded-xl px-4 py-2.5 text-left transition-all hover:-translate-y-0.5"
            style={{
              background: '#FFFFFF',
              border: '1px solid rgba(12,24,38,0.08)',
              boxShadow: '0 1px 3px rgba(12,24,38,0.04)',
            }}
          >
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
              style={{
                background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
                color: 'var(--fc-accent, #0f766e)',
              }}
            >
              {it.count}
            </span>
            <span className="flex flex-col leading-tight">
              <span className="text-[13px] font-medium text-navy-900">{it.label}</span>
              <span className="text-[11.5px] italic text-slate-500" style={{ fontFamily: 'Georgia, serif' }}>
                {it.countLabel}
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
