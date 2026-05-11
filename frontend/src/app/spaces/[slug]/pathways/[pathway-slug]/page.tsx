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
        'group flex items-start gap-4 rounded-xl border px-5 py-4 transition-shadow hover:shadow-[var(--fc-shadow-card)]',
        step.is_completed ? 'border-teal-200 bg-teal-50/40' : 'border-border bg-surface',
      ].join(' ')}
    >
      <div
        className={[
          'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
          step.is_completed
            ? 'bg-teal-500 text-white'
            : 'bg-navy-50 text-navy-400',
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

      <span className="shrink-0 text-slate-300 transition-colors group-hover:text-teal-500">
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
        className="mb-6 inline-block text-sm text-slate-400 hover:text-navy-700"
      >
        ← All Pathways
      </Link>

      <div className="mb-2 h-px w-6 bg-gold-500" />
      <h2 className="mb-2 font-serif text-3xl text-navy-900">{pathway.title}</h2>
      {pathway.description && (
        <p className="mb-6 text-sm leading-relaxed text-slate-500">{pathway.description}</p>
      )}

      {pathway.step_count > 0 && (
        <div className="mb-8">
          <div className="mb-1.5 flex items-baseline justify-between text-xs text-slate-400">
            <span>{pathway.completed_count} of {pathway.step_count} steps complete</span>
            <span>{progressPct}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-navy-100">
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
            className="inline-block rounded-full bg-teal-500 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-teal-600"
          >
            {pathway.completed_count === 0 ? 'Begin' : pathway.completed_count >= pathway.step_count ? 'Review' : 'Continue'}
          </Link>
        </div>
      )}

      {pathway.steps.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface p-6 text-sm text-slate-500">
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
