import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorPathway,
  getCreatorPathwayAboutBlocks,
  getCreatorMedia,
} from '@/lib/serverApi'
import type { PathwayAboutBlock, CreatorMediaAsset } from '@/types/platform'
import AboutPageEditor from '../AboutPageEditor'

interface Props {
  params: Promise<{ pathwaySlug: string }>
}

export default async function EditAboutPage({ params }: Props) {
  const { pathwaySlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const [pathway, blocks, mediaAssets]: [
    Awaited<ReturnType<typeof getCreatorPathway>>,
    PathwayAboutBlock[],
    CreatorMediaAsset[],
  ] = await Promise.all([
    getCreatorPathway(activeSpace.slug, pathwaySlug),
    getCreatorPathwayAboutBlocks(activeSpace.slug, pathwaySlug),
    getCreatorMedia(activeSpace.slug),
  ])

  if (!pathway) notFound()

  return (
    <AboutPageEditor
      spaceSlug={activeSpace.slug}
      pathway={pathway}
      initialBlocks={blocks}
      mediaAssets={mediaAssets}
    />
  )
}
