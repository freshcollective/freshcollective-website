import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorPathway,
  getCreatorPathwayAboutBlocks,
  getCreatorMedia,
  getCreatorResources,
} from '@/lib/serverApi'
import type { PathwayAboutBlock, CreatorMediaAsset, CreatorResource } from '@/types/platform'
import AboutPageEditor from '../AboutPageEditor'

interface Props {
  params: Promise<{ pathwaySlug: string }>
}

export default async function EditAboutPage({ params }: Props) {
  const { pathwaySlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const [pathway, blocks, mediaAssets, resources]: [
    Awaited<ReturnType<typeof getCreatorPathway>>,
    PathwayAboutBlock[],
    CreatorMediaAsset[],
    CreatorResource[],
  ] = await Promise.all([
    getCreatorPathway(activeSpace.slug, pathwaySlug),
    getCreatorPathwayAboutBlocks(activeSpace.slug, pathwaySlug),
    getCreatorMedia(activeSpace.slug),
    getCreatorResources(activeSpace.slug),
  ])

  if (!pathway) notFound()

  return (
    <AboutPageEditor
      spaceSlug={activeSpace.slug}
      pathway={pathway}
      initialBlocks={blocks}
      mediaAssets={mediaAssets}
      resources={resources}
    />
  )
}
