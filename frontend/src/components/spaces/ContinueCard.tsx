import Link from 'next/link'
import type { ContinueResponse } from '@/types/platform'

interface ContinueCardProps {
  data: ContinueResponse | null
  progressPct: number
  stepCount: number
  completedCount: number
  estimatedMinutes?: number | null
}

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
    <Link
      href={href}
      className="group block rounded-2xl border bg-white px-7 py-6 transition-all hover:-translate-y-0.5 hover:shadow-lg"
      style={{ borderColor: 'rgba(56,160,158,0.20)', borderLeft: '3px solid #38A09E' }}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex-1 min-w-0">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em]" style={{ color: '#38A09E' }}>
            {label}
          </p>
          <p className="mb-1 font-serif text-xl text-navy-900 group-hover:text-teal-700 transition-colors">
            {data ? data.step_title : 'Welcome to the REAL Journey'}
          </p>
          {data && (
            <p className="text-sm text-slate-400">{data.pathway_title}</p>
          )}

          {stepCount > 0 && (
            <div className="mt-3">
              <div className="mb-1.5 flex items-center gap-3 text-xs text-slate-400">
                <span>{completedCount} of {stepCount} steps</span>
                {estimatedMinutes && !data?.all_complete && (
                  <span>· ≈ {estimatedMinutes} min</span>
                )}
              </div>
              <div className="h-1.5 w-48 max-w-full overflow-hidden rounded-full bg-navy-100">
                <div
                  className="h-full rounded-full bg-teal-400 transition-all duration-500"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>
          )}
        </div>

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
