import PlanUpgradeNotice from '@/components/creator/PlanUpgradeNotice'
import { getActiveCreatorSpace, getCreatorSpace, getCreatorBilling} from '@/lib/serverApi'
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
  // Plan gate — mirrors the sidebar, which omits this entry entirely on
  // Community. A direct URL is therefore the only way to arrive here on
  // that plan, and it should explain the plan rather than render a tool
  // whose every action the backend will refuse. Not a security
  // boundary: ``app/creator/plan_guards.py`` still owns every write.
  const _billing = await getCreatorBilling().catch(() => null)
  if (!(_billing?.is_platform_owner || _billing?.current_plan?.paid_offers_enabled)) {
    return (
      <PlanUpgradeNotice
        title="Discount Codes"
        intro="Discount codes reduce the price of a paid offer at checkout."
        unlocks="paid offers and the discount codes that go with them"
      />
    )
  }

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
