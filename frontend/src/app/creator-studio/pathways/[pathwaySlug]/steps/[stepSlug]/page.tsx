import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorPathway,
  getCreatorStep,
  getCreatorStepBlocks,
  getCreatorSteps,
  getCreatorMedia,
  getCreatorResources,
  getCreatorSpace,
} from '@/lib/serverApi'
import type { CreatorSpaceDetail, CreatorStep, StepBlock, CreatorMediaAsset, CreatorResource } from '@/types/platform'
import StepBlockEditor from './StepBlockEditor'

interface Props {
  params: Promise<{ pathwaySlug: string; stepSlug: string }>
}

export default async function StepBlockEditorPage({ params }: Props) {
  const { pathwaySlug, stepSlug } = await params
  const space = await getActiveCreatorSpace()
  if (!space) notFound()

  const [pathway, step, blocks, steps, mediaAssets, resources, spaceDetail] = await Promise.all([
    getCreatorPathway(space.slug, pathwaySlug),
    getCreatorStep(space.slug, pathwaySlug, stepSlug),
    getCreatorStepBlocks(space.slug, pathwaySlug, stepSlug),
    getCreatorSteps(space.slug, pathwaySlug),
    getCreatorMedia(space.slug),
    getCreatorResources(space.slug),
    getCreatorSpace(space.slug) as Promise<CreatorSpaceDetail | null>,
  ])

  if (!pathway || !step) notFound()

  // Compute the step's ordinal position and pathway length from data
  // already available; no extra API surface introduced.
  const orderedSteps = steps as CreatorStep[]
  const stepIndex = orderedSteps.findIndex((s) => s.slug === stepSlug)
  const totalSteps = orderedSteps.length

  return (
    <StepBlockEditor
      spaceSlug={space.slug}
      pathway={pathway}
      step={step}
      initialBlocks={blocks as StepBlock[]}
      mediaAssets={mediaAssets as CreatorMediaAsset[]}
      resources={resources as CreatorResource[]}
      stepIndex={stepIndex >= 0 ? stepIndex : null}
      totalSteps={totalSteps}
      collectiveName={space.name}
      collectiveLocation={spaceDetail?.location ?? null}
      collectiveCoverImageUrl={spaceDetail?.cover_image_url ?? null}
    />
  )
}
