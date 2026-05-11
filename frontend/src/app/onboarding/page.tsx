import { redirect } from 'next/navigation'
import { getMe } from '@/lib/serverApi'
import OnboardingFlow from './OnboardingFlow'

export default async function OnboardingPage() {
  const profile = await getMe()

  // Already onboarded — skip to dashboard
  if (profile?.has_completed_onboarding) {
    redirect('/dashboard')
  }

  const firstName = profile?.name?.split(' ')[0] ?? null

  return <OnboardingFlow firstName={firstName} />
}
