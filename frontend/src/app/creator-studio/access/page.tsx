import PlanUpgradeNotice from '@/components/creator/PlanUpgradeNotice'
import { getActiveCreatorSpace, getCreatorPasses, getCreatorSpace, getCreatorBilling} from '@/lib/serverApi'
import type { AccessPassAdminSummary, CreatorSpaceDetail } from '@/types/platform'
import PrimaryActionLink from '@/components/creator/PrimaryActionLink'
import AccessClient from './AccessClient'

/**
 * Creator Studio → Commerce → Access.
 *
 * Renamed from "Memberships" in U1. Route is ``/creator-studio/access``;
 * the previous ``/creator-studio/passes`` URL redirects here for
 * backwards compatibility.
 */
export default async function CreatorAccessPage() {
  // Plan gate — mirrors the sidebar, which omits this entry entirely on
  // Community. A direct URL is therefore the only way to arrive here on
  // that plan, and it should explain the plan rather than render a tool
  // whose every action the backend will refuse. Not a security
  // boundary: ``app/creator/plan_guards.py`` still owns every write.
  const _billing = await getCreatorBilling().catch(() => null)
  if (!(_billing?.is_platform_owner || _billing?.current_plan?.paid_offers_enabled)) {
    return (
      <PlanUpgradeNotice
        title="Access"
        intro="Access records what members hold after buying from you — passes, tickets and allowances."
        unlocks="member checkout, which is what creates access records"
      />
    )
  }

  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">Select a collective first.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Choose a collective from My World to see who has access.
          </p>
          <PrimaryActionLink href="/creator-studio" showIcon={false}>
            Go to My World
          </PrimaryActionLink>
        </div>
      </div>
    )
  }

  const [passes, spaceDetail]: [AccessPassAdminSummary[], CreatorSpaceDetail | null] = await Promise.all([
    getCreatorPasses(activeSpace.slug),
    getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
  ])

  return (
    <AccessClient
      passes={passes}
      spaceName={activeSpace.name}
      spaceSlug={activeSpace.slug}
      headerLocation={spaceDetail?.location ?? null}
      headerCoverImageUrl={spaceDetail?.cover_image_url ?? null}
    />
  )
}
