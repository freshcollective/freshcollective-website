import Link from 'next/link'
import type { PathwayProgress } from '@/types/platform'

interface Props {
  pathway: PathwayProgress
  spaceSlug: string
}

export default function PathwayProgressCard({ pathway, spaceSlug }: Props) {
  const isComingSoon = pathway.status === 'coming_soon'
  const href = `/spaces/${spaceSlug}/pathways/${pathway.slug}`

  const progressPct =
    pathway.step_count > 0
      ? Math.round((pathway.completed_count / pathway.step_count) * 100)
      : 0

  const ctaLabel =
    isComingSoon
      ? null
      : pathway.step_count === 0
        ? 'Explore'
        : pathway.completed_count === 0
          ? 'Begin'
          : pathway.completed_count >= pathway.step_count
            ? 'Review'
            : 'Continue'

  return (
    <div
      className={[
        'flex flex-col overflow-hidden rounded-2xl border',
        isComingSoon ? 'border-border opacity-55' : 'border-border bg-white transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md',
      ].join(' ')}
    >
      {!isComingSoon && (
        <div
          className="h-[3px] w-full shrink-0"
          style={{ background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 100%)' }}
        />
      )}
      <div className="flex flex-1 flex-col p-5">
      <h3
        className={[
          'mb-1.5 font-serif text-lg',
          isComingSoon ? 'text-slate-400' : 'text-navy-900',
        ].join(' ')}
      >
        {pathway.title}
      </h3>

      {pathway.description && (
        <p className="mb-4 line-clamp-2 text-sm leading-relaxed text-slate-500">
          {pathway.description}
        </p>
      )}

      {!isComingSoon && pathway.step_count > 0 && (
        <div className="mb-4">
          <div className="mb-1 flex items-baseline justify-between text-xs text-slate-400">
            <span>{pathway.completed_count} of {pathway.step_count} steps</span>
            <span>{progressPct}%</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-navy-100">
            <div
              className="h-full rounded-full bg-teal-500 transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-auto pt-2">
        {isComingSoon ? (
          <span className="inline-block rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-400">
            Coming Soon
          </span>
        ) : (
          <Link
            href={href}
            className={[
              'inline-block rounded-full px-4 py-1.5 text-sm font-semibold transition-colors',
              pathway.completed_count >= pathway.step_count && pathway.step_count > 0
                ? 'border border-teal-200 text-teal-700 hover:border-teal-400'
                : 'text-white hover:opacity-90',
            ].join(' ')}
            style={
              !(pathway.completed_count >= pathway.step_count && pathway.step_count > 0)
                ? { background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }
                : undefined
            }
          >
            {ctaLabel}
          </Link>
        )}
      </div>
      </div>
    </div>
  )
}
