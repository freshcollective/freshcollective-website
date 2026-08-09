import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import {
  getMe,
  getCreatorSpaces,
  getCreatorSpace,
  ACTIVE_SPACE_COOKIE,
} from '@/lib/serverApi'
import CreatorStudioShell from './CreatorStudioShell'
import CollectiveThemeProvider from '@/components/collective/CollectiveThemeProvider'
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

  // CollectiveThemeProvider composes the palette React context AND
  // sets the palette-scoped CSS custom properties (--fc-accent,
  // --fc-accent-soft, --fc-accent-line, --fc-accent-strong). Editor
  // previews (BlockPreview, reflection-prompt renderings, callout
  // fallbacks) read those vars — without them the previews all
  // fall back to teal regardless of the collective's chosen palette.
  return (
    <CollectiveThemeProvider palette={palette}>
      <CreatorStudioShell user={profile} hasCollective={!!activeSpace}>
        {children}
      </CreatorStudioShell>
    </CollectiveThemeProvider>
  )
}
