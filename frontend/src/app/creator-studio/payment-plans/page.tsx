import { getCreatorBilling } from '@/lib/serverApi'
import CreatorPaymentPlansClient from './CreatorPaymentPlansClient'

export const metadata = { title: 'Payment Plans — Creator Studio' }

export default async function CreatorPaymentPlansPage() {
  const billing = await getCreatorBilling()
  const isPlatformOwner = billing?.is_platform_owner ?? false
  return <CreatorPaymentPlansClient isPlatformOwner={isPlatformOwner} />
}
