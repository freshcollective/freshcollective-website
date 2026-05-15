import Link from 'next/link'
import type { PathwayProgress } from '@/types/platform'

// Same deterministic gradients as PathwayCard
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
          ? 'border-border bg-white opacity-55'
          : 'border-border bg-white transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md',
      ].join(' ')}
    >
      {/* Mini cover */}
      <div
        className="relative h-20 shrink-0 overflow-hidden"
        style={{
          background: isComingSoon
            ? 'linear-gradient(135deg, #94a3b8 0%, #cbd5e1 100%)'
            : coverGradient(pathway.slug),
        }}
      >
        <div
          className="absolute inset-0"
          style={{ background: 'radial-gradient(ellipse at 80% 20%, rgba(255,255,255,0.07) 0%, transparent 60%)' }}
        />
        <div className="absolute inset-0 flex items-center px-4">
          <p className="font-serif text-base leading-snug text-white line-clamp-2">{pathway.title}</p>
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
            <span className="inline-block rounded-full bg-slate-100 px-3 py-1 text-[11px] text-slate-400">
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
