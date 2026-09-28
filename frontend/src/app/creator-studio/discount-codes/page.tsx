import { getActiveCreatorSpace, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import DiscountCodesClient from './DiscountCodesClient'

/**
 * Creator Studio → Commerce → Discount Codes.
 *
 * Sits immediately after Payment Options: a code discounts an offer, so
 * it belongs beside the offers rather than with the ledger surfaces.
 *
 * The server component establishes the active Collective so the artwork
 * header paints immediately; the client hydrates the list from
 * ``GET /api/creator/spaces/{slug}/discount-codes``.
 */
export default async function DiscountCodesPage() {
  const activeSpace = await getActiveCreatorSpace()
  const spaceDetail: CreatorSpaceDetail | null = activeSpace
    ? ((await getCreatorSpace(activeSpace.slug)) as CreatorSpaceDetail | null)
    : null

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <h1 className="font-serif text-2xl text-navy-900">Discount codes</h1>
        <p className="mt-2 text-[14px] text-slate-600">
          Choose a Collective from My World to manage its discount codes.
        </p>
      </div>
    )
  }

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      <CollectiveArtworkHeader
        collectiveName={activeSpace.name}
        sectionTitle="Discount codes"
        meta={
          <>
            Offer a reduced price on what you sell. A member enters the code
            at checkout and pays less.
          </>
        }
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
      />
      <DiscountCodesClient
        spaceSlug={activeSpace.slug}
        defaultCurrency={spaceDetail?.pricing_currency ?? 'AUD'}
      />
    </div>
  )
}
