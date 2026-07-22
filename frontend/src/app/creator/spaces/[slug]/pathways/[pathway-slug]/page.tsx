import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getCreatorPathway, getCreatorSteps } from '@/lib/serverApi'
import type { CreatorStep } from '@/types/platform'
import PathwayForm from './PathwayForm'
import StepList from './StepList'

export default async function CreatorPathwayPage({
  params,
}: {
  params: Promise<{ slug: string; 'pathway-slug': string }>
}) {
  const { slug, 'pathway-slug': pathwaySlug } = await params
  const [pathway, steps] = await Promise.all([
    getCreatorPathway(slug, pathwaySlug),
    getCreatorSteps(slug, pathwaySlug),
  ])
  if (!pathway) notFound()

  return (
    <div className="max-w-2xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">{pathway.title}</h1>
        <div className="mt-1 flex items-center gap-3">
          <p className="text-sm text-black">{steps.length} step{steps.length !== 1 ? 's' : ''}</p>
          <Link
            href={`/spaces/${slug}/pathways/${pathwaySlug}`}
            target="_blank"
            className="text-xs text-teal-600 hover:underline"
          >
            Preview ↗
          </Link>
        </div>
      </div>

      <PathwayForm pathway={pathway} spaceSlug={slug} />

      <div className="mt-12">
        <div className="mb-1 h-px w-6 bg-gold-400" />
        <h2 className="mb-5 font-serif text-xl text-navy-900">Steps</h2>
        <StepList steps={steps as CreatorStep[]} spaceSlug={slug} pathwaySlug={pathwaySlug} />
      </div>
    </div>
  )
}
