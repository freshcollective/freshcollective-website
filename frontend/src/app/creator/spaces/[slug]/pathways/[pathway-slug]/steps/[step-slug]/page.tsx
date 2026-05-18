import { notFound } from 'next/navigation'
import {
  getCreatorStep,
  getCreatorPathway,
  getCreatorStepBlocks,
  getCreatorMedia,
} from '@/lib/serverApi'
import StepBlockEditor from '@/app/creator-studio/pathways/[pathwaySlug]/steps/[stepSlug]/StepBlockEditor'
import type { StepBlock, CreatorMediaAsset } from '@/types/platform'

export default async function CreatorStepPage({
  params,
}: {
  params: Promise<{ slug: string; 'pathway-slug': string; 'step-slug': string }>
}) {
  const { slug, 'pathway-slug': pathwaySlug, 'step-slug': stepSlug } = await params

  const [step, pathway, blocks, mediaAssets] = await Promise.all([
    getCreatorStep(slug, pathwaySlug, stepSlug),
    getCreatorPathway(slug, pathwaySlug),
    getCreatorStepBlocks(slug, pathwaySlug, stepSlug),
    getCreatorMedia(slug),
  ])

  if (!step || !pathway) notFound()

  return (
    <StepBlockEditor
      spaceSlug={slug}
      pathway={pathway}
      step={step}
      initialBlocks={blocks as StepBlock[]}
      mediaAssets={mediaAssets as CreatorMediaAsset[]}
      backHref={`/creator/spaces/${slug}/pathways/${pathwaySlug}`}
      backLabel="← Back to pathway"
    />
  )
}
