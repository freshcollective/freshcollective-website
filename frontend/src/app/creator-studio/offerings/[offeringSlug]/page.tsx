import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorOffering,
  getCreatorOfferingReadiness,
  getCreatorSpace,
  getOfferingCovers,
} from '@/lib/serverApi'
import type {
  CreatorOffering, CreatorSpaceDetail, OfferingCover, OfferingReadiness,
} from '@/types/platform'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import OfferingHeader from './OfferingHeader'
import OfferingDetailsClient from './OfferingDetailsClient'

interface Props {
  params: Promise<{ offeringSlug: string }>
}

/** 🌸 Details — title, short description and cover image. */
export default async function OfferingDetailsPage({ params }: Props) {
  const { offeringSlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const [offering, readiness, covers, spaceDetail]: [
    CreatorOffering | null,
    OfferingReadiness | null,
    OfferingCover[],
    CreatorSpaceDetail | null,
  ] = await Promise.all([
    getCreatorOffering(activeSpace.slug, offeringSlug),
    getCreatorOfferingReadiness(activeSpace.slug, offeringSlug),
    getOfferingCovers(),
    getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
  ])

  if (!offering) notFound()

  return (
    <CreatorPageContainer>
      <OfferingHeader
        active="details"
        spaceSlug={activeSpace.slug}
        spaceName={activeSpace.name}
        offering={offering}
        readiness={readiness}
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
      />
      <OfferingDetailsClient
        spaceSlug={activeSpace.slug}
        offering={offering}
        covers={covers}
      />
    </CreatorPageContainer>
  )
}
