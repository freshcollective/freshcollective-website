import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorOffering,
  getCreatorOfferingReadiness,
  getCreatorSpace,
} from '@/lib/serverApi'
import type {
  CreatorOffering, CreatorSpaceDetail, OfferingReadiness,
} from '@/types/platform'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import OfferingHeader from '../OfferingHeader'
import OfferingPricingClient from './OfferingPricingClient'

interface Props {
  params: Promise<{ offeringSlug: string }>
}

/** 💛 Pricing — Free or one-time purchase. */
export default async function OfferingPricingPage({ params }: Props) {
  const { offeringSlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const [offering, readiness, spaceDetail]: [
    CreatorOffering | null, OfferingReadiness | null, CreatorSpaceDetail | null,
  ] = await Promise.all([
    getCreatorOffering(activeSpace.slug, offeringSlug),
    getCreatorOfferingReadiness(activeSpace.slug, offeringSlug),
    getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
  ])

  if (!offering) notFound()

  return (
    <CreatorPageContainer>
      <OfferingHeader
        active="pricing"
        spaceSlug={activeSpace.slug}
        spaceName={activeSpace.name}
        offering={offering}
        readiness={readiness}
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
      />
      <OfferingPricingClient
        spaceSlug={activeSpace.slug}
        offering={offering}
        readiness={readiness}
      />
    </CreatorPageContainer>
  )
}
