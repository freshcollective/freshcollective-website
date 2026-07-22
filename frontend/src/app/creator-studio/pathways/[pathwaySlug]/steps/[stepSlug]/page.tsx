import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorPathway,
  getCreatorStep,
  getCreatorStepBlocks,
  getCreatorMedia,
  getCreatorResources,
} from '@/lib/serverApi'
import type { StepBlock, CreatorMediaAsset, CreatorResource } from '@/types/platform'
import StepBlockEditor from './StepBlockEditor'

interface Props {
  params: Promise<{ pathwaySlug: string; stepSlug: string }>
}

export default async function StepBlockEditorPage({ params }: Props) {
  const { pathwaySlug, stepSlug } = await params
  const space = await getActiveCreatorSpace()
  if (!space) notFound()

  const [pathway, step, blocks, mediaAssets, resources] = await Promise.all([
    getCreatorPathway(space.slug, pathwaySlug),
    getCreatorStep(space.slug, pathwaySlug, stepSlug),
    getCreatorStepBlocks(space.slug, pathwaySlug, stepSlug),
    getCreatorMedia(space.slug),
    getCreatorResources(space.slug),
  ])

  if (!pathway || !step) notFound()

  return (
    <StepBlockEditor
      spaceSlug={space.slug}
      pathway={pathway}
      step={step}
      initialBlocks={blocks as StepBlock[]}
      mediaAssets={mediaAssets as CreatorMediaAsset[]}
      resources={resources as CreatorResource[]}
    />
  )
}
