import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getStep, getSteps, getPathway } from '@/lib/serverApi'
import StepActions from '@/components/spaces/StepActions'
import type { StepDetail, StepSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string; 'step-slug': string }>
}

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text: 'Read',
  reflection: 'Reflect',
  exercise: 'Exercise',
  video: 'Watch',
  audio: 'Listen',
}

function renderContent(body: string): React.ReactNode {
  return body
    .split('\n\n')
    .map((block, i) => {
      const trimmed = block.trim()
      if (!trimmed) return null

      if (trimmed.startsWith('**') && trimmed.endsWith('**') && !trimmed.slice(2, -2).includes('\n')) {
        return (
          <h3 key={i} className="mt-8 mb-3 font-serif text-xl text-navy-900">
            {trimmed.slice(2, -2)}
          </h3>
        )
      }

      if (trimmed === '---') {
        return <hr key={i} className="my-8 border-border" />
      }

      if (trimmed.split('\n').every((l) => l.trimStart().startsWith('- '))) {
        const items = trimmed.split('\n').map((l) => l.replace(/^- /, '').trim())
        return (
          <ul key={i} className="my-4 space-y-2 pl-5">
            {items.map((item, j) => (
              <li
                key={j}
                className="relative text-[15px] leading-[1.8] text-slate-600 before:absolute before:-left-5 before:text-slate-300 before:content-['–']"
              >
                {item}
              </li>
            ))}
          </ul>
        )
      }

      const parts = trimmed.split(/(\*\*[^*]+\*\*)/)
      return (
        <p key={i} className="my-4 text-[15px] leading-[1.85] text-slate-600">
          {parts.map((part, j) =>
            part.startsWith('**') && part.endsWith('**') ? (
              <strong key={j} className="font-semibold text-navy-800">
                {part.slice(2, -2)}
              </strong>
            ) : (
              part
            ),
          )}
        </p>
      )
    })
    .filter(Boolean)
}

export default async function StepPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug, 'step-slug': stepSlug } = await params

  const [step, allSteps, pathway]: [StepDetail | null, StepSummary[], { title: string } | null] =
    await Promise.all([
      getStep(slug, pathwaySlug, stepSlug),
      getSteps(slug, pathwaySlug),
      getPathway(slug, pathwaySlug),
    ])

  if (!step) notFound()

  const currentIndex = allSteps.findIndex((s) => s.slug === stepSlug)
  const prevStep = currentIndex > 0 ? allSteps[currentIndex - 1] : null
  const nextStep = currentIndex < allSteps.length - 1 ? allSteps[currentIndex + 1] : null

  const pathwayHref = `/spaces/${slug}/pathways/${pathwaySlug}`
  const pathwayTitle = pathway?.title ?? 'Pathway'
  const completedCount = allSteps.filter((s) => s.is_completed).length
  const totalCount = allSteps.length

  return (
    <div className="mx-auto max-w-[680px]">

      {/* Breadcrumb */}
      <div className="mb-8 flex items-center gap-2 text-sm text-slate-400">
        <Link href={pathwayHref} className="hover:text-navy-700 transition-colors">
          {pathwayTitle}
        </Link>
        <span className="text-slate-200">/</span>
        <span className="text-slate-500 line-clamp-1">{step.title}</span>
      </div>

      {/* Progress strip */}
      <div className="mb-10">
        <div className="mb-2 flex items-baseline justify-between text-xs text-slate-400">
          <span>{completedCount} of {totalCount} complete</span>
          <span>Step {step.position} of {totalCount}</span>
        </div>
        <div className="h-0.5 w-full overflow-hidden rounded-full bg-navy-100">
          <div
            className="h-full rounded-full bg-teal-400 transition-all duration-500"
            style={{ width: `${totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0}%` }}
          />
        </div>
      </div>

      {/* Step header */}
      <div className="mb-10">
        <div className="mb-2 flex items-center gap-2 text-xs text-slate-400">
          <span className="font-medium uppercase tracking-wider">
            {CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type}
          </span>
          {step.estimated_minutes && (
            <>
              <span className="text-slate-200">·</span>
              <span>{step.estimated_minutes} min</span>
            </>
          )}
        </div>
        <div className="mb-3 h-px w-8 bg-gold-400" />
        <h1 className="font-serif text-3xl leading-snug text-navy-900 md:text-4xl">
          {step.title}
        </h1>
      </div>

      {/* Content */}
      {step.content_body && (
        <article className="mb-2 border-b border-border pb-2">
          {renderContent(step.content_body)}
        </article>
      )}

      {/* Notes + complete */}
      <StepActions
        spaceSlug={slug}
        pathwaySlug={pathwaySlug}
        stepSlug={stepSlug}
        isCompleted={step.is_completed}
        initialNotes={step.reflection_text}
      />

      {/* Prev / Next */}
      <div className="mt-10 flex items-center justify-between border-t border-border pt-6">
        {prevStep ? (
          <Link
            href={`/spaces/${slug}/pathways/${pathwaySlug}/${prevStep.slug}`}
            className="group flex items-center gap-2 text-sm text-slate-400 transition-colors hover:text-navy-700"
          >
            <span>←</span>
            <span className="hidden sm:inline group-hover:underline underline-offset-2">
              {prevStep.title}
            </span>
            <span className="sm:hidden">Previous</span>
          </Link>
        ) : (
          <Link href={pathwayHref} className="text-sm text-slate-400 hover:text-navy-700 transition-colors">
            ← {pathwayTitle}
          </Link>
        )}

        {nextStep ? (
          <Link
            href={`/spaces/${slug}/pathways/${pathwaySlug}/${nextStep.slug}`}
            className="group flex items-center gap-2 text-sm font-medium text-teal-600 transition-colors hover:text-teal-700"
          >
            <span className="hidden sm:inline group-hover:underline underline-offset-2">
              {nextStep.title}
            </span>
            <span className="sm:hidden">Next</span>
            <span>→</span>
          </Link>
        ) : (
          <Link
            href={pathwayHref}
            className="text-sm font-medium text-teal-600 hover:underline underline-offset-2"
          >
            Back to {pathwayTitle} →
          </Link>
        )}
      </div>
    </div>
  )
}
