import Link from 'next/link'
import type { PathwaySummary } from '@/types/platform'

// Lighter, softer deterministic covers — same slug always gives same gradient.
// All variants fade to light/white so dark navy text is always readable.
const COVERS = [
  'linear-gradient(135deg, #42C7C6 0%, #EAF8F7 58%, #FFFFFF 100%)',
  'linear-gradient(135deg, #EAF8F7 0%, #FFFFFF 50%, #DDF5F3 100%)',
  'linear-gradient(135deg, #0F8F8D 0%, #42C7C6 38%, #EAF8F7 75%, #FFFFFF 100%)',
  'linear-gradient(135deg, #38A09E 0%, #7FCFCD 42%, #F2FBFA 80%, #FFFFFF 100%)',
  'linear-gradient(135deg, #F2FBFA 0%, #EAF8F7 55%, #FAFAF8 100%)',
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
          ? 'border-border bg-white opacity-65'
          : 'border-border bg-white transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-lg',
      ].join(' ')}
    >
      {/* Visual cover area */}
      <div
        className="relative h-28 shrink-0 overflow-hidden"
        style={{
          background: isComingSoon
            ? 'linear-gradient(135deg, #EEF9F8 0%, #E8F5F5 50%, #F4FAFA 100%)'
            : coverGradient(pathway.slug),
        }}
      >
        {/* Subtle radial glow overlay */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'radial-gradient(circle at 90% 10%, rgba(56,160,158,0.20), transparent 40%), ' +
              'radial-gradient(circle at 10% 85%, rgba(66,199,198,0.10), transparent 30%)',
          }}
        />
        <div className="absolute inset-0 flex flex-col justify-end px-5 pb-4">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-teal-600">
            {isComingSoon ? 'Coming soon' : 'Pathway'}
          </p>
          <p className="font-serif text-[17px] leading-snug text-navy-900 line-clamp-2">
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
