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
        'flex flex-col rounded-xl border p-5',
        isComingSoon ? 'border-border opacity-55' : 'border-border bg-surface',
      ].join(' ')}
    >
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
              'inline-block rounded-full px-4 py-1.5 text-sm font-medium transition-colors',
              pathway.completed_count >= pathway.step_count && pathway.step_count > 0
                ? 'border border-navy-200 text-navy-600 hover:border-navy-400'
                : 'bg-teal-500 text-white hover:bg-teal-600',
            ].join(' ')}
          >
            {ctaLabel}
          </Link>
        )}
      </div>
    </div>
  )
}
