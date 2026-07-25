import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import {
  getMe,
  getCreatorSpaces,
  getCreatorSpace,
  getCreatorBilling,
  ACTIVE_SPACE_COOKIE,
} from '@/lib/serverApi'
import CreatorStudioShell from './CreatorStudioShell'
import { CollectivePaletteContextProvider } from '@/components/collective/CollectivePaletteContext'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import type { CreatorSpaceDetail, SpaceSummary } from '@/types/platform'

export const metadata = { title: 'Creator Studio — Fresh Collective' }

export default async function CreatorStudioLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false
  if (!authenticated) redirect('/login')

  const profile = await getMe()
  if (!profile || !['creator', 'admin'].includes(profile.role)) {
    redirect('/dashboard')
  }

  const spaces: SpaceSummary[] = await getCreatorSpaces()
  const activeSlug = cookieStore.get(ACTIVE_SPACE_COOKIE)?.value
  const activeSpace = (activeSlug ? spaces.find(s => s.slug === activeSlug) : null) ?? spaces[0] ?? null

  const billing = await getCreatorBilling()
  const isPlatformOwner = billing?.is_platform_owner ?? false
  // Platform Owner has no plan, so no numeric limit — the sidebar reads
  // this alongside `isPlatformOwner` and treats the limit as absent when
  // the flag is true. For Creators the value comes from their current plan.
  const collectiveLimit = billing?.current_plan?.collective_limit ?? 1

  // Hydrate the active space's palette so the shared colour picker
  // (callouts, container tint, buttons, text/highlight shortcuts)
  // resolves against the correct collective everywhere under
  // /creator-studio/*. Switching collectives changes the active-space
  // cookie; the next navigation re-fetches with the new slug so
  // palette leakage between collectives is not possible.
  //
  // Deliberately null when there's no active space (new creator, no
  // collective yet) — the picker falls back to the "More colours…"
  // hex flow only.
  let palette: CollectivePaletteMeta | null = null
  let activeLocationThumbnail: string | null = null
  if (activeSpace) {
    try {
      const detail = await getCreatorSpace(activeSpace.slug) as CreatorSpaceDetail | null
      palette = detail?.colour_palette ?? null
      // Atlas v1.2 — the sidebar's switcher renders the Location
      // thumbnail so the identity of the active collective is legible
      // at a glance. Prefer the thumbnail; fall back to the hero if
      // no thumbnail has been curated for this Location.
      activeLocationThumbnail =
        detail?.location?.thumbnail_artwork_url
          ?? detail?.location?.hero_artwork_url
          ?? null
    } catch (err) {
      console.error(`[creator-studio/layout] palette fetch failed for ${activeSpace.slug}:`, err)
    }
  }

  return (
    <CollectivePaletteContextProvider palette={palette}>
      <CreatorStudioShell
        user={profile}
        spaces={spaces}
        activeSpace={activeSpace}
        collectiveLimit={collectiveLimit}
        isPlatformOwner={isPlatformOwner}
        activeLocationThumbnail={activeLocationThumbnail}
      >
        {children}
      </CreatorStudioShell>
    </CollectivePaletteContextProvider>
  )
}
