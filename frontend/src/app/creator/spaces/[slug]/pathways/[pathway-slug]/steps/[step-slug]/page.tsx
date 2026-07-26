import { notFound } from 'next/navigation'
import {
  getCreatorStep,
  getCreatorPathway,
  getCreatorStepBlocks,
  getCreatorMedia,
  getCreatorResources,
  getCreatorSpace,
} from '@/lib/serverApi'
import StepBlockEditor from '@/app/creator-studio/pathways/[pathwaySlug]/steps/[stepSlug]/StepBlockEditor'
import type { CreatorSpaceDetail, StepBlock, CreatorMediaAsset, CreatorResource } from '@/types/platform'

export default async function CreatorStepPage({
  params,
}: {
  params: Promise<{ slug: string; 'pathway-slug': string; 'step-slug': string }>
}) {
  const { slug, 'pathway-slug': pathwaySlug, 'step-slug': stepSlug } = await params

  const [step, pathway, blocks, mediaAssets, resources, spaceDetail] = await Promise.all([
    getCreatorStep(slug, pathwaySlug, stepSlug),
    getCreatorPathway(slug, pathwaySlug),
    getCreatorStepBlocks(slug, pathwaySlug, stepSlug),
    getCreatorMedia(slug),
    getCreatorResources(slug),
    getCreatorSpace(slug) as Promise<CreatorSpaceDetail | null>,
  ])

  if (!step || !pathway) notFound()

  return (
    <StepBlockEditor
      spaceSlug={slug}
      pathway={pathway}
      step={step}
      initialBlocks={blocks as StepBlock[]}
      mediaAssets={mediaAssets as CreatorMediaAsset[]}
      resources={resources as CreatorResource[]}
      backHref={`/creator/spaces/${slug}/pathways/${pathwaySlug}`}
      backLabel="← Back to pathway"
      collectiveName={spaceDetail?.name ?? slug}
      collectiveLocation={spaceDetail?.location ?? null}
      collectiveCoverImageUrl={spaceDetail?.cover_image_url ?? null}
    />
  )
}
