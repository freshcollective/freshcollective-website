import Link from 'next/link'
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
        'overflow-hidden rounded-2xl border',
        isComingSoon ? 'border-border bg-surface opacity-60' : 'border-border bg-white transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md',
      ].join(' ')}
    >
      {!isComingSoon && (
        <div
          className="h-[3px] w-full"
          style={{ background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 100%)' }}
        />
      )}
      <div className="p-6">
      <h3
        className={[
          'mb-2 font-serif text-xl',
          isComingSoon ? 'text-slate-400' : 'text-navy-900',
        ].join(' ')}
      >
        {pathway.title}
      </h3>
      {pathway.description && (
        <p className="mb-4 text-sm leading-relaxed text-slate-500">{pathway.description}</p>
      )}
      {isComingSoon ? (
        <span className="inline-block rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-400">
          Coming Soon
        </span>
      ) : (
        <Link
          href={href}
          className="inline-block rounded-full px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Start
        </Link>
      )}
      </div>
    </div>
  )
}
