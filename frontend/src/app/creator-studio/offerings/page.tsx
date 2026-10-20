import {
  getActiveCreatorSpace,
  getCreatorOfferings,
  getCreatorSpace,
} from '@/lib/serverApi'
import type { CreatorOffering, CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import OfferingsClient from './OfferingsClient'

/**
 * Creator Studio → Offerings.
 *
 * Deliberately the same shape as ``/creator-studio/pathways/page.tsx``:
 * the artwork header carrying the Collective's identity, a primary
 * action, and a client component holding the list. A creator moving
 * between the two surfaces should not have to learn a second layout.
 *
 * The "create" action lives inside the client rather than in the header
 * here, because creating an Offering is a one-field inline action — a
 * title, then straight into the editor — where creating a Pathway has
 * its own ``/new`` page with type and access choices to make first.
 */
export default async function OfferingsPage() {
  const activeSpace = await getActiveCreatorSpace()

  const [offerings, spaceDetail]: [CreatorOffering[], CreatorSpaceDetail | null] =
    activeSpace
      ? await Promise.all([
          getCreatorOfferings(activeSpace.slug),
          getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
        ])
      : [[], null]

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      {activeSpace && (
        <CollectiveArtworkHeader
          collectiveName={activeSpace.name}
          sectionTitle="Offerings"
          meta={<>Digital resources people can download — workbooks, audio, templates.</>}
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
        />
      )}

      {!activeSpace && (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Offerings</h1>
          <p className="mt-2 text-[15px] leading-relaxed text-black">
            Digital resources people can download — workbooks, audio, templates.
          </p>
        </div>
      )}

      <OfferingsClient
        initialOfferings={offerings}
        activeSpace={activeSpace}
        collectiveDetail={spaceDetail}
      />
    </div>
  )
}
