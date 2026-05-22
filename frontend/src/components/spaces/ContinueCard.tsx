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
    : '/spaces/the-natural-leader-hub/pathways/real-journey'

  const label = data?.all_complete
    ? 'Journey complete'
    : completedCount === 0
      ? 'Begin your journey'
      : 'Continue your journey'

  const cta = data?.all_complete ? 'Review' : completedCount === 0 ? 'Begin' : 'Continue'

  return (
    <Link
      href={href}
      className={`group flex flex-col overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-2xl ${className}`}
      style={{
        background:
          'radial-gradient(circle at 72% 18%, rgba(85,215,210,0.06) 0%, transparent 28%), ' +
          '#071824',
        border: '1px solid rgba(66,199,198,0.12)',
        boxShadow: '0 8px 40px rgba(7,24,36,0.32), 0 2px 8px rgba(0,0,0,0.16)',
      }}
    >
      <div className="flex flex-1 flex-col px-7 py-7 md:px-8 md:py-8">
        {/* Soft gold accent line */}
        <div
          className="mb-4 h-[2px] w-6 rounded-full"
          style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
        />

        {/* Label — soft white */}
        <p
          className="mb-3 text-[10px] font-semibold uppercase tracking-[0.18em]"
          style={{ color: 'rgba(255,255,255,0.78)' }}
        >
          {label}
        </p>

        {/* Step title — sans-serif, teal-to-white gradient, more white than teal */}
        <p
          className="font-sans font-semibold text-2xl leading-snug transition-opacity group-hover:opacity-80 md:text-3xl"
          style={{
            letterSpacing: '-0.02em',
            background: 'linear-gradient(90deg, #55D7D2 0%, #BDF7F5 35%, #FFFFFF 75%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
          }}
        >
          {data ? data.step_title : 'Welcome to the REAL Journey'}
        </p>

        {/* Pathway name — muted white */}
        {data && (
          <p className="mt-2 text-[13px]" style={{ color: 'rgba(255,255,255,0.72)' }}>
            {data.pathway_title}
          </p>
        )}

        {/* Progress */}
        {stepCount > 0 && (
          <div className="mt-4">
            <div
              className="mb-1.5 flex items-center gap-3 text-[11px]"
              style={{ color: 'rgba(255,255,255,0.68)' }}
            >
              <span>{completedCount} of {stepCount} steps</span>
              {estimatedMinutes && !data?.all_complete && (
                <span>· ≈ {estimatedMinutes} min</span>
              )}
            </div>
            <div
              className="h-1.5 w-48 max-w-full overflow-hidden rounded-full"
              style={{ background: 'rgba(255,255,255,0.14)' }}
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

        {/* CTA pinned to bottom */}
        <div className="mt-auto pt-6">
          <span
            className="inline-flex items-center gap-1.5 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {cta} →
          </span>
        </div>
      </div>
    </Link>
  )
}
