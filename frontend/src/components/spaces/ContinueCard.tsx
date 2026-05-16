import Link from 'next/link'
import type { ContinueResponse } from '@/types/platform'

interface ContinueCardProps {
  data: ContinueResponse | null
  progressPct: number
  stepCount: number
  completedCount: number
  estimatedMinutes?: number | null
  className?: string
}

export default function ContinueCard({
  data,
  progressPct,
  stepCount,
  completedCount,
  estimatedMinutes,
  className = '',
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
      className={`group relative flex flex-col overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-md ${className}`}
      style={{
        background: '#EAF7F6',
        border: '1px solid rgba(56,160,158,0.16)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      }}
    >
      {/* Large faint decorative arrow */}
      <div
        className="pointer-events-none absolute right-5 top-4 select-none font-serif text-[80px] font-bold leading-none"
        style={{ color: 'rgba(56,160,158,0.08)' }}
        aria-hidden="true"
      >
        →
      </div>

      {/* flex-1 so CTA is anchored to bottom when card stretches */}
      <div className="relative flex flex-1 flex-col px-6 py-6 md:px-7 md:py-7">
        <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
          {label}
        </p>

        <p className="font-serif text-2xl leading-snug text-navy-900 transition-colors group-hover:text-teal-700 md:text-3xl">
          {data ? data.step_title : 'Welcome to the REAL Journey'}
        </p>

        {data && (
          <p className="mt-1.5 text-[13px] text-slate-500">
            {data.pathway_title}
          </p>
        )}

        {stepCount > 0 && (
          <div className="mt-4">
            <div className="mb-1.5 flex items-center gap-3 text-[11px] text-slate-400">
              <span>{completedCount} of {stepCount} steps</span>
              {estimatedMinutes && !data?.all_complete && (
                <span>· ≈ {estimatedMinutes} min</span>
              )}
            </div>
            <div
              className="h-1.5 w-48 max-w-full overflow-hidden rounded-full"
              style={{ background: 'rgba(56,160,158,0.15)' }}
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

        <div className="mt-auto pt-5">
          <span
            className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {cta} →
          </span>
        </div>
      </div>
    </Link>
  )
}
