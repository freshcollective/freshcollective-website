import { redirect } from 'next/navigation'
import { getPublicPlatformArtwork, buildPlatformArtLookup } from '@/lib/serverApi'
import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import OnboardingFlow from './OnboardingFlow'

interface Props {
  searchParams: Promise<{ revisit?: string }>
}

export default async function OnboardingPage({ searchParams }: Props) {
  // Shared guard closes the "valid JWT + gone User row" gap that lets
  // a stale session render the onboarding UI with an empty name.
  const profile = await requireAuthenticatedUser({ fallbackNext: '/onboarding' })

  const [artwork, params] = await Promise.all([
    getPublicPlatformArtwork(),
    searchParams,
  ])

  // Already onboarded — skip to dashboard, unless the member is
  // intentionally revisiting the introduction (from Settings → Profile).
  const isRevisit = params.revisit === '1'
  if (profile.has_completed_onboarding && !isRevisit) {
    redirect('/dashboard')
  }

  const firstName = profile.name?.split(' ')[0] ?? null
  const artFor = buildPlatformArtLookup(artwork)

  return (
    <OnboardingFlow
      firstName={firstName}
      heroArt={{
        welcome:     artFor('member_onboarding_welcome'),
        interests:   artFor('member_onboarding_interests'),
        howItWorks:  artFor('member_onboarding_how_it_works'),
        arrival:     artFor('member_onboarding_arrival'),
      }}
    />
  )
}
