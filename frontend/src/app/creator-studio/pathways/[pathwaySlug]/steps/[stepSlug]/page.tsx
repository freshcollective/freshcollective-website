import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorPathway,
  getCreatorStep,
  getCreatorStepBlocks,
  getCreatorMedia,
} from '@/lib/serverApi'
import type { StepBlock, CreatorMediaAsset } from '@/types/platform'
import StepBlockEditor from './StepBlockEditor'

interface Props {
  params: Promise<{ pathwaySlug: string; stepSlug: string }>
}

export default async function StepBlockEditorPage({ params }: Props) {
  const { pathwaySlug, stepSlug } = await params
  const space = await getActiveCreatorSpace()
  if (!space) notFound()

  const [pathway, step, blocks, mediaAssets] = await Promise.all([
    getCreatorPathway(space.slug, pathwaySlug),
    getCreatorStep(space.slug, pathwaySlug, stepSlug),
    getCreatorStepBlocks(space.slug, pathwaySlug, stepSlug),
    getCreatorMedia(space.slug),
  ])

  if (!pathway || !step) notFound()

  return (
    <StepBlockEditor
      spaceSlug={space.slug}
      pathway={pathway}
      step={step}
      initialBlocks={blocks as StepBlock[]}
      mediaAssets={mediaAssets as CreatorMediaAsset[]}
    />
  )
}
