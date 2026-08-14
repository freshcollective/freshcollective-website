import { getActiveCreatorSpace, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import NewPaymentOptionClient from './NewPaymentOptionClient'

/**
 * Creator Studio → Commerce → Payment Options → New.
 *
 * A minimal create form. Once the row is created the user is
 * redirected into ``/creator-studio/payment-options/{id}`` where
 * they add grants + schedules.
 */
export default async function NewPaymentOptionPage() {
  const activeSpace = await getActiveCreatorSpace()
  const spaceDetail: CreatorSpaceDetail | null = activeSpace
    ? ((await getCreatorSpace(activeSpace.slug)) as CreatorSpaceDetail | null)
    : null

  return (
    <div className="w-full max-w-[820px] px-8 py-8 md:px-10 md:py-10">
      {activeSpace && (
        <CollectiveArtworkHeader
          collectiveName={activeSpace.name}
          sectionTitle="New Payment Option"
          meta={<>Give it a name to start. You'll add included experiences and payment methods next.</>}
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
          backLink={{ href: '/creator-studio/payment-options', label: 'Back to Payment Options' }}
        />
      )}

      {activeSpace && <NewPaymentOptionClient spaceSlug={activeSpace.slug} />}
    </div>
  )
}
