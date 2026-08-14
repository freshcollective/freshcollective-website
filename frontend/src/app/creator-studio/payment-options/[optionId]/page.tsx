import { getActiveCreatorSpace, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import PaymentOptionEditorClient from './PaymentOptionEditorClient'

interface Props {
  params: Promise<{ optionId: string }>
}

/**
 * Creator Studio → Commerce → Payment Options → Edit.
 *
 * Server component renders the header. The client component
 * hydrates the full option (with grants + schedules embedded)
 * and provides the editor surface.
 */
export default async function PaymentOptionEditorPage({ params }: Props) {
  const { optionId } = await params
  const activeSpace = await getActiveCreatorSpace()
  const spaceDetail: CreatorSpaceDetail | null = activeSpace
    ? ((await getCreatorSpace(activeSpace.slug)) as CreatorSpaceDetail | null)
    : null

  return (
    <div className="w-full max-w-[980px] px-8 py-8 md:px-10 md:py-10">
      {activeSpace && (
        <CollectiveArtworkHeader
          collectiveName={activeSpace.name}
          sectionTitle="Payment Option"
          meta={<>Manage what's included and how members pay.</>}
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
          backLink={{ href: '/creator-studio/payment-options', label: 'Back to Payment Options' }}
        />
      )}
      {activeSpace && (
        <PaymentOptionEditorClient spaceSlug={activeSpace.slug} optionId={optionId} />
      )}
    </div>
  )
}
