import Link from 'next/link'
import type { PathwaySummary } from '@/types/platform'

// Deterministic cover gradient — same slug always gets the same gradient
const COVERS = [
  'linear-gradient(135deg, #073B3A 0%, #0F5E5C 100%)',
  'linear-gradient(135deg, #071824 0%, #073B3A 100%)',
  'linear-gradient(135deg, #0F5E5C 0%, #38A09E 100%)',
  'linear-gradient(135deg, #062F35 0%, #0A5759 100%)',
  'linear-gradient(135deg, #0A5759 0%, #2d9096 100%)',
]

function coverGradient(slug: string): string {
  let h = 0
  for (let i = 0; i < slug.length; i++) h = ((h << 5) - h + slug.charCodeAt(i)) | 0
  return COVERS[Math.abs(h) % COVERS.length]
}

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
        'flex flex-col overflow-hidden rounded-2xl border',
        isComingSoon
          ? 'border-border bg-white opacity-60'
          : 'border-border bg-white transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-lg',
      ].join(' ')}
    >
      {/* Visual cover area */}
      <div
        className="relative h-28 shrink-0 overflow-hidden"
        style={{
          background: isComingSoon
            ? 'linear-gradient(135deg, #94a3b8 0%, #cbd5e1 100%)'
            : coverGradient(pathway.slug),
        }}
      >
        {/* Subtle texture overlay */}
        <div
          className="absolute inset-0"
          style={{ background: 'radial-gradient(ellipse at 80% 20%, rgba(255,255,255,0.07) 0%, transparent 60%)' }}
        />
        <div className="absolute inset-0 flex flex-col justify-end px-5 pb-4">
          <p
            className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em]"
            style={{ color: 'rgba(255,255,255,0.55)' }}
          >
            {isComingSoon ? 'Coming soon' : 'Pathway'}
          </p>
          <p className="font-serif text-lg leading-snug text-white line-clamp-2">
            {pathway.title}
          </p>
        </div>
      </div>

      {/* Card body */}
      <div className="flex flex-1 flex-col p-5">
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
              className="text-[13px] font-semibold text-teal-700 transition-colors hover:text-teal-800"
            >
              Start →
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}
