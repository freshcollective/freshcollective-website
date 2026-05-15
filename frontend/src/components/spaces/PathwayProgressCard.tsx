import Link from 'next/link'
import type { PathwayProgress } from '@/types/platform'

// Same lighter gradients — dark navy text always readable at bottom of cover
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
        isComingSoon
          ? 'border-border bg-white opacity-60'
          : 'border-border bg-white transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md',
      ].join(' ')}
    >
      {/* Mini cover */}
      <div
        className="relative h-20 shrink-0 overflow-hidden"
        style={{
          background: isComingSoon
            ? 'linear-gradient(135deg, #EEF9F8 0%, #E8F5F5 50%, #F4FAFA 100%)'
            : coverGradient(pathway.slug),
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            background: 'radial-gradient(circle at 90% 10%, rgba(56,160,158,0.18), transparent 40%)',
          }}
        />
        <div className="absolute inset-0 flex items-center px-4">
          <p className="font-serif text-[15px] leading-snug text-navy-900 line-clamp-2">
            {pathway.title}
          </p>
        </div>
      </div>

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

        <div className="mt-auto pt-1">
          {isComingSoon ? (
            <span className="inline-block rounded-full bg-teal-50 px-3 py-1 text-[11px] text-teal-600">
              Coming Soon
            </span>
          ) : (
            <Link
              href={href}
              className="inline-block rounded-full px-4 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              {ctaLabel}
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}
