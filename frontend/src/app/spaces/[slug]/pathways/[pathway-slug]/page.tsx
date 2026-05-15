import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview } from '@/lib/serverApi'
import type { PathwayWithSteps, StepSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
}

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text: 'Read',
  reflection: 'Reflect',
  exercise: 'Exercise',
  video: 'Watch',
  audio: 'Listen',
}

// Deterministic cover gradient
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

function StepRow({
  step,
  spaceSlug,
  pathwaySlug,
  index,
}: {
  step: StepSummary
  spaceSlug: string
  pathwaySlug: string
  index: number
}) {
  const href = `/spaces/${spaceSlug}/pathways/${pathwaySlug}/${step.slug}`

  return (
    <Link
      href={href}
      className={[
        'group flex items-start gap-4 rounded-2xl border px-5 py-4 transition-all hover:-translate-y-0.5 hover:shadow-sm',
        step.is_completed
          ? 'border-teal-200 bg-teal-50/40 hover:border-teal-300'
          : 'border-border bg-white hover:border-teal-200',
      ].join(' ')}
    >
      <div
        className={[
          'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
          step.is_completed
            ? 'bg-teal-500 text-white'
            : 'bg-teal-50 text-teal-600',
        ].join(' ')}
      >
        {step.is_completed ? '✓' : index + 1}
      </div>

      <div className="min-w-0 flex-1">
        <p
          className={[
            'font-medium leading-snug',
            step.is_completed ? 'text-teal-700' : 'text-navy-900',
          ].join(' ')}
        >
          {step.title}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-400">
          <span>{CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type}</span>
          {step.estimated_minutes && <span>{step.estimated_minutes} min</span>}
        </div>
      </div>

      <span className="shrink-0 self-center text-slate-300 transition-colors group-hover:text-teal-500">
        →
      </span>
    </Link>
  )
}

export default async function PathwayDetailPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params
  const pathway: PathwayWithSteps | null = await getPathwayOverview(slug, pathwaySlug)

  if (!pathway) notFound()

  const progressPct =
    pathway.step_count > 0
      ? Math.round((pathway.completed_count / pathway.step_count) * 100)
      : 0

  const nextIncomplete = pathway.steps.find((s) => !s.is_completed)
  const continueHref = nextIncomplete
    ? `/spaces/${slug}/pathways/${pathwaySlug}/${nextIncomplete.slug}`
    : `/spaces/${slug}/pathways/${pathwaySlug}/${pathway.steps[0]?.slug}`

  return (
    <div className="max-w-2xl">
      <Link
        href={`/spaces/${slug}/pathways`}
        className="mb-6 inline-block text-sm text-slate-400 transition-colors hover:text-teal-600"
      >
        ← All Pathways
      </Link>

      {/* Visual pathway banner — light gradient, dark text */}
      <div
        className="mb-6 overflow-hidden rounded-2xl border border-teal-100"
        style={{ background: coverGradient(pathwaySlug) }}
      >
        <div
          className="px-7 py-8"
          style={{
            background:
              'radial-gradient(circle at 90% 10%, rgba(56,160,158,0.18), transparent 40%), ' +
              'radial-gradient(circle at 10% 85%, rgba(66,199,198,0.10), transparent 30%)',
          }}
        >
          <div className="mb-3 h-[2px] w-8 rounded-full bg-teal-400" />
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-teal-600">
            Pathway
          </p>
          <h2 className="font-serif text-2xl text-navy-900 md:text-3xl">{pathway.title}</h2>
          {pathway.description && (
            <p className="mt-2 max-w-md text-[14px] leading-relaxed text-slate-600">
              {pathway.description}
            </p>
          )}
        </div>
      </div>

      {pathway.step_count > 0 && (
        <div className="mb-8">
          <div className="mb-1.5 flex items-baseline justify-between text-xs text-slate-400">
            <span>{pathway.completed_count} of {pathway.step_count} steps complete</span>
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

      {pathway.steps.length > 0 && continueHref && (
        <div className="mb-8">
          <Link
            href={continueHref}
            className="inline-block rounded-full px-5 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {pathway.completed_count === 0 ? 'Begin' : pathway.completed_count >= pathway.step_count ? 'Review' : 'Continue'}
          </Link>
        </div>
      )}

      {pathway.steps.length === 0 ? (
        <div className="rounded-2xl border border-teal-100 bg-white p-6 text-sm text-slate-500">
          Steps for this pathway are coming soon.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {pathway.steps.map((step, i) => (
            <StepRow
              key={step.id}
              step={step}
              spaceSlug={slug}
              pathwaySlug={pathwaySlug}
              index={i}
            />
          ))}
        </div>
      )}
    </div>
  )
}
