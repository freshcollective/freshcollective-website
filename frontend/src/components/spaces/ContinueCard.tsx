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
      className="group flex flex-col overflow-hidden rounded-xl transition-all hover:brightness-110"
      style={{
        background: 'rgba(255,255,255,0.10)',
        border: '1px solid rgba(255,255,255,0.14)',
      }}
    >
      {/* Teal accent bar at top */}
      <div
        className="h-[3px] w-full"
        style={{ background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 60%, transparent 100%)' }}
      />

      <div className="flex flex-1 flex-col p-5">
        {/* Pill label */}
        <span
          className="mb-3 inline-flex w-fit items-center rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
          style={{ background: 'rgba(56,160,158,0.25)', color: '#6DD9D8' }}
        >
          {label}
        </span>

        {/* Large serif step title */}
        <p
          className="font-serif text-2xl leading-snug transition-opacity group-hover:opacity-80 md:text-3xl"
          style={{ color: '#FFFFFF' }}
        >
          {data ? data.step_title : 'Welcome to the REAL Journey'}
        </p>

        {/* Pathway name */}
        {data && (
          <p className="mt-1 text-[13px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
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

        {/* CTA */}
        <div className="mt-auto pt-5">
          <span
            className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-[13px] font-semibold transition-opacity group-hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)', color: '#FFFFFF' }}
          >
            {cta} →
          </span>
        </div>
      </div>
    </Link>
  )
}
