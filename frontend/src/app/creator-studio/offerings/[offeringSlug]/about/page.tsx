import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorMedia,
  getCreatorOffering,
  getCreatorOfferingAboutBlocks,
  getCreatorOfferingReadiness,
  getCreatorResources,
  getCreatorSpace,
} from '@/lib/serverApi'
import type {
  CreatorMediaAsset, CreatorOffering, CreatorResource, CreatorSpaceDetail,
  OfferingReadiness, PathwayAboutBlock,
} from '@/types/platform'
import { apiUrl } from '@/lib/api'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import AboutPageEditor from '../../../pathways/[pathwaySlug]/AboutPageEditor'
import OfferingHeader from '../OfferingHeader'

interface Props {
  params: Promise<{ offeringSlug: string }>
}

/**
 * ✨ About — optional rich-content presentation.
 *
 * This page writes **no editor of its own**. It mounts the existing
 * ``AboutPageEditor`` and points it at the Offering's own blocks
 * endpoint through the ``blocksApiUrl`` override the Gathering Series
 * work already added for exactly this purpose.
 *
 * Everything the Pathway About page can do, this can do — columns,
 * images, headings, text, links, callouts, buttons, embeds — because it
 * is the same component writing the same ``pathway_about_blocks`` rows,
 * rendered on the member side by the same ``AboutBlockRenderer``. No
 * capability is reduced and nothing is duplicated.
 *
 * The section stays optional: ``offering_readiness`` has no ``about``
 * requirement, so an Offering can be published with this page empty.
 */
export default async function OfferingAboutPage({ params }: Props) {
  const { offeringSlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const [offering, blocks, readiness, mediaAssets, resources, spaceDetail]: [
    CreatorOffering | null,
    PathwayAboutBlock[],
    OfferingReadiness | null,
    CreatorMediaAsset[],
    CreatorResource[],
    CreatorSpaceDetail | null,
  ] = await Promise.all([
    getCreatorOffering(activeSpace.slug, offeringSlug),
    getCreatorOfferingAboutBlocks(activeSpace.slug, offeringSlug),
    getCreatorOfferingReadiness(activeSpace.slug, offeringSlug),
    getCreatorMedia(activeSpace.slug),
    getCreatorResources(activeSpace.slug),
    getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
  ])

  if (!offering) notFound()

  return (
    <CreatorPageContainer>
      <OfferingHeader
        active="about"
        spaceSlug={activeSpace.slug}
        spaceName={activeSpace.name}
        offering={offering}
        readiness={readiness}
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
      />
      <AboutPageEditor
        spaceSlug={activeSpace.slug}
        initialBlocks={blocks}
        mediaAssets={mediaAssets}
        resources={resources}
        blocksApiUrl={apiUrl(
          `/api/creator/spaces/${activeSpace.slug}/offerings/${offering.slug}/about-blocks`,
        )}
        previewHref={`/spaces/${activeSpace.slug}/offerings/${offering.slug}`}
        headingTitle="About this Offering"
        headingBody="Optional. Add anything that helps someone decide — what's inside, who it's for, how to use it."
        emptyStateHeading="No extra detail yet"
        emptyStateBody="This is optional. The title, description and cover are often enough; add blocks here if you want to say more."
      />
    </CreatorPageContainer>
  )
}
