import PlanUpgradeNotice from '@/components/creator/PlanUpgradeNotice'
import { getActiveCreatorSpace, getCreatorBilling } from '@/lib/serverApi'
import CreatorPaymentPlansClient from './CreatorPaymentPlansClient'

export const metadata = { title: 'Payment Plans — Creator Studio' }

export default async function CreatorPaymentPlansPage() {
  // Plan gate — mirrors the sidebar, which omits this entry entirely on
  // Community. A direct URL is therefore the only way to arrive here on
  // that plan, and it should explain the plan rather than render a tool
  // whose every action the backend will refuse. Not a security
  // boundary: ``app/creator/plan_guards.py`` still owns every write.
  const _billing = await getCreatorBilling().catch(() => null)
  if (!(_billing?.is_platform_owner || _billing?.current_plan?.paid_offers_enabled)) {
    return (
      <PlanUpgradeNotice
        title="Payment Plans"
        intro="Payment Plans track members paying for an offer in instalments."
        unlocks="instalment payment plans and member checkout"
      />
    )
  }

  const [billing, activeSpace] = await Promise.all([
    getCreatorBilling(),
    getActiveCreatorSpace(),
  ])
  const isPlatformOwner = billing?.is_platform_owner ?? false
  return (
    <CreatorPaymentPlansClient
      isPlatformOwner={isPlatformOwner}
      spaceSlug={activeSpace?.slug ?? null}
    />
  )
}
