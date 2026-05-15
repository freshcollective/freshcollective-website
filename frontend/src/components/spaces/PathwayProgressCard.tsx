import Link from 'next/link'
import PathwayCover from '@/components/ui/PathwayCover'
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

  const ctaLabel = isComingSoon
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
        'group flex flex-col overflow-hidden rounded-2xl border border-border bg-white',
        isComingSoon
          ? 'opacity-70'
          : 'shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg hover:border-teal-200/60',
      ].join(' ')}
    >
      {/* Visual cover */}
      <PathwayCover
        slug={pathway.slug}
        title={pathway.title}
        coverImageUrl={pathway.cover_image_url}
        isComingSoon={isComingSoon}
      />

      {/* Card body */}
      <div className="flex flex-1 flex-col p-4">
        {pathway.description && (
          <p className="mb-3 line-clamp-2 text-[12px] leading-relaxed text-slate-500">
            {pathway.description}
          </p>
        )}

        {!isComingSoon && pathway.step_count > 0 && (
          <div className="mb-3">
            <div className="mb-1 flex items-baseline justify-between text-[11px] text-slate-400">
              <span>{pathway.completed_count} of {pathway.step_count} steps</span>
              <span>{progressPct}%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-teal-100">
              <div
                className="h-full rounded-full bg-teal-500 transition-all"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}

        <div className="mt-auto border-t border-border pt-3">
          {isComingSoon ? (
            <span className="text-[11px] text-slate-400">Coming soon</span>
          ) : (
            <Link
              href={href}
              className="text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800"
            >
              {ctaLabel} →
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}
