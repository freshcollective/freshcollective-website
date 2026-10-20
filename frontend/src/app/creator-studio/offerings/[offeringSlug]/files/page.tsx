import { notFound } from 'next/navigation'
import {
  getActiveCreatorSpace,
  getCreatorOffering,
  getCreatorOfferingFiles,
  getCreatorOfferingReadiness,
  getCreatorSpace,
} from '@/lib/serverApi'
import type {
  CreatorOffering, CreatorSpaceDetail, OfferingFileList, OfferingReadiness,
} from '@/types/platform'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import OfferingHeader from '../OfferingHeader'
import OfferingFilesClient from './OfferingFilesClient'

interface Props {
  params: Promise<{ offeringSlug: string }>
}

/** 📦 Files — upload, describe, reorder, replace and remove resources. */
export default async function OfferingFilesPage({ params }: Props) {
  const { offeringSlug } = await params
  const activeSpace = await getActiveCreatorSpace()
  if (!activeSpace) notFound()

  const [offering, files, readiness, spaceDetail]: [
    CreatorOffering | null,
    OfferingFileList | null,
    OfferingReadiness | null,
    CreatorSpaceDetail | null,
  ] = await Promise.all([
    getCreatorOffering(activeSpace.slug, offeringSlug),
    getCreatorOfferingFiles(activeSpace.slug, offeringSlug),
    getCreatorOfferingReadiness(activeSpace.slug, offeringSlug),
    getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
  ])

  if (!offering) notFound()

  return (
    <CreatorPageContainer>
      <OfferingHeader
        active="files"
        spaceSlug={activeSpace.slug}
        spaceName={activeSpace.name}
        offering={offering}
        readiness={readiness}
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
      />
      <OfferingFilesClient
        spaceSlug={activeSpace.slug}
        offeringSlug={offering.slug}
        initial={files}
      />
    </CreatorPageContainer>
  )
}
