import { notFound } from 'next/navigation'
import PreviewClient, { type ScreenKey } from './PreviewClient'

/**
 * Development-only preview harness for the Creator onboarding
 * presentation components. Renders the real production components with
 * mocked props so visual/copy work can be reviewed without creating
 * database records.
 *
 * Guard: any non-development NODE_ENV (production, test) returns 404.
 * The route is still compiled into the bundle, but requesting it in
 * production yields a Not Found response — never a preview.
 */

const VALID_SCREENS: readonly ScreenKey[] = ['welcome', 'final']

interface Props {
  searchParams: { screen?: string }
}

export default function OnboardingPreviewPage({ searchParams }: Props) {
  if (process.env.NODE_ENV !== 'development') {
    notFound()
  }

  const requested = searchParams.screen
  const initial: ScreenKey = (VALID_SCREENS as readonly string[]).includes(requested ?? '')
    ? (requested as ScreenKey)
    : 'welcome'

  return <PreviewClient initial={initial} />
}

export const metadata = {
  title: 'Onboarding preview · dev',
  robots: { index: false, follow: false },
}
