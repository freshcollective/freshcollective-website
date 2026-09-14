import { getActiveCreatorSpace, getCreatorBilling } from '@/lib/serverApi'
import CreatorPaymentPlansClient from './CreatorPaymentPlansClient'

export const metadata = { title: 'Payment Plans — Creator Studio' }

export default async function CreatorPaymentPlansPage() {
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
