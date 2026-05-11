import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getStep, getSteps } from '@/lib/serverApi'
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

      // Heading: **text**
      if (trimmed.startsWith('**') && trimmed.endsWith('**') && !trimmed.slice(2, -2).includes('\n')) {
        return (
          <h3 key={i} className="mt-6 mb-2 font-serif text-lg text-navy-900">
            {trimmed.slice(2, -2)}
          </h3>
        )
      }

      // Horizontal rule
      if (trimmed === '---') {
        return <hr key={i} className="my-6 border-border" />
      }

      // Bullet list block
      if (trimmed.split('\n').every((l) => l.trimStart().startsWith('- '))) {
        const items = trimmed.split('\n').map((l) => l.replace(/^- /, '').trim())
        return (
          <ul key={i} className="my-3 space-y-1 pl-4">
            {items.map((item, j) => (
              <li key={j} className="relative text-sm leading-relaxed text-slate-600 before:absolute before:-left-4 before:text-slate-300 before:content-['–']">
                {item}
              </li>
            ))}
          </ul>
        )
      }

      // Bold inline markers **text**
      const parts = trimmed.split(/(\*\*[^*]+\*\*)/)
      return (
        <p key={i} className="my-3 text-[15px] leading-[1.8] text-slate-600">
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

  const [step, allSteps]: [StepDetail | null, StepSummary[]] = await Promise.all([
    getStep(slug, pathwaySlug, stepSlug),
    getSteps(slug, pathwaySlug),
  ])

  if (!step) notFound()

  const currentIndex = allSteps.findIndex((s) => s.slug === stepSlug)
  const prevStep = currentIndex > 0 ? allSteps[currentIndex - 1] : null
  const nextStep = currentIndex < allSteps.length - 1 ? allSteps[currentIndex + 1] : null

  const pathwayHref = `/spaces/${slug}/pathways/${pathwaySlug}`
  const completedCount = allSteps.filter((s) => s.is_completed).length

  return (
    <div className="mx-auto max-w-[680px]">
      {/* Breadcrumb */}
      <div className="mb-8 flex items-center gap-2 text-sm text-slate-400">
        <Link href={pathwayHref} className="hover:text-navy-700">
          REAL Journey
        </Link>
        <span>/</span>
        <span className="text-slate-500">{step.title}</span>
      </div>

      {/* Progress strip */}
      <div className="mb-8">
        <div className="mb-1 flex items-baseline justify-between text-xs text-slate-400">
          <span>{completedCount} of {allSteps.length} complete</span>
          <span>Step {step.position} of {allSteps.length}</span>
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-navy-100">
          <div
            className="h-full rounded-full bg-teal-500 transition-all"
            style={{ width: `${allSteps.length > 0 ? Math.round((completedCount / allSteps.length) * 100) : 0}%` }}
          />
        </div>
      </div>

      {/* Step header */}
      <div className="mb-8">
        <div className="mb-1 flex items-center gap-2 text-xs text-slate-400">
          <span>{CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type}</span>
          {step.estimated_minutes && (
            <>
              <span>·</span>
              <span>{step.estimated_minutes} min</span>
            </>
          )}
        </div>
        <div className="mb-3 h-px w-6 bg-gold-500" />
        <h1 className="font-serif text-3xl leading-snug text-navy-900">{step.title}</h1>
      </div>

      {/* Content */}
      {step.content_body && (
        <article className="mb-2">
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
            className="flex items-center gap-2 text-sm text-slate-400 hover:text-navy-700"
          >
            <span>←</span>
            <span className="hidden sm:inline">{prevStep.title}</span>
            <span className="sm:hidden">Previous</span>
          </Link>
        ) : (
          <Link href={pathwayHref} className="text-sm text-slate-400 hover:text-navy-700">
            ← Pathway
          </Link>
        )}

        {nextStep ? (
          <Link
            href={`/spaces/${slug}/pathways/${pathwaySlug}/${nextStep.slug}`}
            className="flex items-center gap-2 text-sm text-slate-400 hover:text-navy-700"
          >
            <span className="hidden sm:inline">{nextStep.title}</span>
            <span className="sm:hidden">Next</span>
            <span>→</span>
          </Link>
        ) : (
          <Link href={pathwayHref} className="text-sm text-teal-600 hover:underline">
            Back to Pathway →
          </Link>
        )}
      </div>
    </div>
  )
}
