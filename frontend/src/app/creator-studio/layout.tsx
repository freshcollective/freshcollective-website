import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import {
  getCreatorSpaces,
  getCreatorSpace,
  getCreatorBilling,
  ACTIVE_SPACE_COOKIE,
} from '@/lib/serverApi'
import CreatorStudioShell from './CreatorStudioShell'
import CollectiveThemeProvider from '@/components/collective/CollectiveThemeProvider'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import type { CreatorSpaceDetail, SpaceSummary } from '@/types/platform'

export const metadata = { title: 'Creator Studio — Fresh Collective' }

export default async function CreatorStudioLayout({ children }: { children: React.ReactNode }) {
  // Shared guard: a null user (deleted / rolled-back account) redirects
  // to /login with ``next`` preserved. A wrong role (authenticated
  // member) then falls through to /dashboard — preserving the previous
  // "non-creator lands on Your World" behaviour.
  const profile = await requireAuthenticatedUser()
  if (!['creator', 'admin'].includes(profile.role)) {
    redirect('/dashboard')
  }

  const cookieStore = await cookies()

  const spaces: SpaceSummary[] = await getCreatorSpaces()
  const activeSlug = cookieStore.get(ACTIVE_SPACE_COOKIE)?.value
  const activeSpace = (activeSlug ? spaces.find(s => s.slug === activeSlug) : null) ?? spaces[0] ?? null

  // Hydrate the active space's palette so the shared colour picker
  // (callouts, container tint, buttons, text/highlight shortcuts)
  // resolves against the correct collective everywhere under
  // /creator-studio/*. Switching collectives (via My World) changes
  // the active-space cookie; the next navigation re-fetches with the
  // new slug so palette leakage between collectives is not possible.
  let palette: CollectivePaletteMeta | null = null
  if (activeSpace) {
    try {
      const detail = await getCreatorSpace(activeSpace.slug) as CreatorSpaceDetail | null
      palette = detail?.colour_palette ?? null
    } catch (err) {
      console.error(`[creator-studio/layout] palette fetch failed for ${activeSpace.slug}:`, err)
    }
  }

  // Plan-tier flag — used to hide commercial-only sidebar items on
  // Community plan and to render an upgrade page instead of the
  // editor when a Community creator direct-navigates to those routes.
  // Platform Owner (``is_platform_owner=true``) always sees the
  // commercial surface. A billing fetch failure defaults to false so
  // we err on hiding rather than exposing a paywalled surface with
  // no guardrail.
  let paidOffersEnabled = false
  try {
    const billing = await getCreatorBilling()
    if (billing) {
      paidOffersEnabled = !!(
        billing.is_platform_owner
        || billing.current_plan?.paid_offers_enabled
      )
    }
  } catch (err) {
    console.error('[creator-studio/layout] billing fetch failed:', err)
  }

  // CollectiveThemeProvider composes the palette React context AND
  // sets the palette-scoped CSS custom properties (--fc-accent,
  // --fc-accent-soft, --fc-accent-line, --fc-accent-strong). Editor
  // previews (BlockPreview, reflection-prompt renderings, callout
  // fallbacks) read those vars — without them the previews all
  // fall back to teal regardless of the collective's chosen palette.
  return (
    <CollectiveThemeProvider palette={palette}>
      <CreatorStudioShell
        user={profile}
        hasCollective={!!activeSpace}
        paidOffersEnabled={paidOffersEnabled}
      >
        {children}
      </CreatorStudioShell>
    </CollectiveThemeProvider>
  )
}
