import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorPathway,
  getCreatorPathwayAboutBlocks,
  getCreatorMedia,
  getCreatorResources,
  getCreatorSteps,
} from '@/lib/serverApi'
import type { PathwayAboutBlock, CreatorMediaAsset, CreatorResource, CreatorStep } from '@/types/platform'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import AboutPageEditor from '../AboutPageEditor'
import PathwayHeader from '../PathwayHeader'

interface Props {
  params: Promise<{ pathwaySlug: string }>
}

export default async function EditAboutPage({ params }: Props) {
  const { pathwaySlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const [pathway, blocks, mediaAssets, resources, steps]: [
    Awaited<ReturnType<typeof getCreatorPathway>>,
    PathwayAboutBlock[],
    CreatorMediaAsset[],
    CreatorResource[],
    CreatorStep[],
  ] = await Promise.all([
    getCreatorPathway(activeSpace.slug, pathwaySlug),
    getCreatorPathwayAboutBlocks(activeSpace.slug, pathwaySlug),
    getCreatorMedia(activeSpace.slug),
    getCreatorResources(activeSpace.slug),
    getCreatorSteps(activeSpace.slug, pathwaySlug),
  ])

  if (!pathway) notFound()

  const hasManualStep = steps.some((s) => s.release_type === 'manual')

  return (
    <CreatorPageContainer>
      <PathwayHeader
        active="about"
        spaceSlug={activeSpace.slug}
        spaceName={activeSpace.name}
        pathway={pathway}
        showManualReleases={hasManualStep}
      />
      <AboutPageEditor
        spaceSlug={activeSpace.slug}
        pathway={pathway}
        initialBlocks={blocks}
        mediaAssets={mediaAssets}
        resources={resources}
      />
    </CreatorPageContainer>
  )
}
