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
        'rounded-xl border bg-surface p-6',
        isComingSoon ? 'border-border opacity-60' : 'border-border shadow-[var(--fc-shadow-card)]',
      ].join(' ')}
    >
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
          className="inline-block rounded-full bg-teal-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-teal-600"
        >
          Start
        </Link>
      )}
    </div>
  )
}
