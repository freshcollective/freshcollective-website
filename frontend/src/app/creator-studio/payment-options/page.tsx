import PlanUpgradeNotice from '@/components/creator/PlanUpgradeNotice'
import { getActiveCreatorSpace, getCreatorSpace, getCreatorBilling} from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import PrimaryActionLink from '@/components/creator/PrimaryActionLink'
import PaymentOptionsIndexClient from './PaymentOptionsIndexClient'

/**
 * Creator Studio → Commerce → Payment Options.
 *
 * The Collective-scoped, grants-first authoring surface. Replaces
 * the legacy per-Pathway / per-Series Payment Option CRUD as the
 * primary Creator entry point.
 *
 * Server component only fetches the active-collective identity so
 * the artwork header renders on first paint. The client component
 * hydrates the list from
 * ``GET /api/creator/spaces/{slug}/commerce/payment-options``.
 */
export default async function PaymentOptionsPage() {
  // Plan gate — mirrors the sidebar, which omits this entry entirely on
  // Community. A direct URL is therefore the only way to arrive here on
  // that plan, and it should explain the plan rather than render a tool
  // whose every action the backend will refuse. Not a security
  // boundary: ``app/creator/plan_guards.py`` still owns every write.
  const _billing = await getCreatorBilling().catch(() => null)
  if (!(_billing?.is_platform_owner || _billing?.current_plan?.paid_offers_enabled)) {
    return (
      <PlanUpgradeNotice
        title="Payment Options"
        intro="Payment Options are how you price and sell what you offer — one-off, instalments or subscription."
        unlocks="paid offers, instalment plans and member checkout"
      />
    )
  }

  const activeSpace = await getActiveCreatorSpace()
  const spaceDetail: CreatorSpaceDetail | null = activeSpace
    ? ((await getCreatorSpace(activeSpace.slug)) as CreatorSpaceDetail | null)
    : null

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      {activeSpace && (
        <CollectiveArtworkHeader
          collectiveName={activeSpace.name}
          sectionTitle="Payment Options"
          meta={
            <>
              Bundle the experiences you sell — Pathways, Gathering Series,
              Gatherings — and set how members can pay.
            </>
          }
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
          action={
            <PrimaryActionLink href="/creator-studio/payment-options/new">
              New Payment Option
            </PrimaryActionLink>
          }
        />
      )}

      {!activeSpace && (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Payment Options</h1>
          <p className="mt-2 text-[15px] leading-relaxed text-black">
            Payment Options belong to a Collective. Create a Collective from
            My World first.
          </p>
        </div>
      )}

      {activeSpace && <PaymentOptionsIndexClient spaceSlug={activeSpace.slug} />}
    </div>
  )
}
