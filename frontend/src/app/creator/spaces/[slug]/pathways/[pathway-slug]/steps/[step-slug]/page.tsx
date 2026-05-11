import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getCreatorStep, getCreatorPathway } from '@/lib/serverApi'
import StepEditor from './StepEditor'

export default async function CreatorStepPage({
  params,
}: {
  params: Promise<{ slug: string; 'pathway-slug': string; 'step-slug': string }>
}) {
  const { slug, 'pathway-slug': pathwaySlug, 'step-slug': stepSlug } = await params
  const [step, pathway] = await Promise.all([
    getCreatorStep(slug, pathwaySlug, stepSlug),
    getCreatorPathway(slug, pathwaySlug),
  ])
  if (!step || !pathway) notFound()

  return (
    <div className="max-w-2xl">
      <div className="mb-2 flex items-center gap-2 text-xs text-slate-400">
        <Link href={`/creator/spaces/${slug}/pathways`} className="hover:text-navy-700">
          Pathways
        </Link>
        <span>/</span>
        <Link href={`/creator/spaces/${slug}/pathways/${pathwaySlug}`} className="hover:text-navy-700">
          {pathway.title}
        </Link>
        <span>/</span>
        <span className="text-slate-500">{step.title}</span>
      </div>
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <div className="mb-2 h-px w-6 bg-gold-400" />
          <h1 className="font-serif text-2xl text-navy-900">Edit step</h1>
        </div>
        <Link
          href={`/spaces/${slug}/pathways/${pathwaySlug}/${stepSlug}`}
          target="_blank"
          className="shrink-0 text-xs text-teal-600 hover:underline"
        >
          Preview ↗
        </Link>
      </div>

      <StepEditor step={step} spaceSlug={slug} pathwaySlug={pathwaySlug} />
    </div>
  )
}
