import Link from 'next/link'
import PathwayCover from '@/components/ui/PathwayCover'
import type { PathwaySummary } from '@/types/platform'

interface PathwayCardProps {
  pathway: PathwaySummary
  spaceSlug: string
}

export default function PathwayCard({ pathway, spaceSlug }: PathwayCardProps) {
  const isComingSoon = pathway.status === 'coming_soon'
  const href = `/spaces/${spaceSlug}/pathways/${pathway.slug}`

  return (
    <div
      className={[
        'group flex flex-col overflow-hidden rounded-2xl border border-border bg-white',
        isComingSoon
          ? 'opacity-70'
          : 'shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg hover:border-teal-200/60',
      ].join(' ')}
    >
      {/* Visual cover tile */}
      <PathwayCover
        slug={pathway.slug}
        title={pathway.title}
        coverImageUrl={pathway.cover_image_url}
        isComingSoon={isComingSoon}
      />

      {/* Card body */}
      <div className="flex flex-1 flex-col p-4">
        {pathway.description ? (
          <p className="mb-4 flex-1 text-[13px] leading-relaxed text-slate-500 line-clamp-2">
            {pathway.description}
          </p>
        ) : (
          <div className="flex-1" />
        )}

        <div className="flex items-center justify-between border-t border-border pt-3">
          {isComingSoon ? (
            <span className="text-[11px] text-slate-400">Coming soon</span>
          ) : (
            <Link
              href={href}
              className="text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800"
            >
              Start →
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}
