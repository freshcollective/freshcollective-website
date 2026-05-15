import Link from 'next/link'
import type { ContinueResponse } from '@/types/platform'

interface ContinueCardProps {
  data: ContinueResponse | null
  progressPct: number
  stepCount: number
  completedCount: number
  estimatedMinutes?: number | null
}

/**
 * Renders journey progress content directly onto its parent background.
 * Parent is expected to be a dark ocean panel — this component uses white/light
 * text colours throughout so it reads clearly on dark.
 */
export default function ContinueCard({
  data,
  progressPct,
  stepCount,
  completedCount,
  estimatedMinutes,
}: ContinueCardProps) {
  const href = data
    ? `/spaces/${data.space_slug}/pathways/${data.pathway_slug}/${data.step_slug}`
    : '/spaces/fresh-collective/pathways/real-journey'

  const label = data?.all_complete
    ? 'Journey complete'
    : completedCount === 0
      ? 'Begin your journey'
      : 'Continue your journey'

  const cta = data?.all_complete ? 'Review' : completedCount === 0 ? 'Begin' : 'Continue'

  return (
    <Link href={href} className="group block">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">

        <div className="min-w-0 flex-1">
          {/* Pill label — teal on dark bg */}
          <span
            className="mb-3 inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
            style={{ background: 'rgba(56,160,158,0.25)', color: '#6DD9D8' }}
          >
            {label}
          </span>

          {/* Large serif step title in white */}
          <p className="font-serif text-2xl leading-snug text-white transition-opacity group-hover:opacity-80 md:text-3xl">
            {data ? data.step_title : 'Welcome to the REAL Journey'}
          </p>

          {/* Pathway name */}
          {data && (
            <p className="mt-1 text-[13px]" style={{ color: 'rgba(255,255,255,0.52)' }}>
              {data.pathway_title}
            </p>
          )}

          {/* Progress */}
          {stepCount > 0 && (
            <div className="mt-4">
              <div
                className="mb-1.5 flex items-center gap-3 text-[11px]"
                style={{ color: 'rgba(255,255,255,0.45)' }}
              >
                <span>{completedCount} of {stepCount} steps</span>
                {estimatedMinutes && !data?.all_complete && (
                  <span>· ≈ {estimatedMinutes} min</span>
                )}
              </div>
              <div
                className="h-1.5 w-48 max-w-full overflow-hidden rounded-full"
                style={{ background: 'rgba(255,255,255,0.15)' }}
              >
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${progressPct}%`,
                    background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 100%)',
                  }}
                />
              </div>
            </div>
          )}
        </div>

        {/* CTA button */}
        <div className="shrink-0">
          <span
            className="inline-flex items-center gap-1.5 rounded-xl px-5 py-2.5 text-sm font-semibold text-white transition-opacity group-hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {cta}
            <span aria-hidden="true">→</span>
          </span>
        </div>

      </div>
    </Link>
  )
}
