import FirstArrivalOverlay from '@/components/build/FirstArrivalOverlay'
import CollectiveThemeProvider from '@/components/collective/CollectiveThemeProvider'
import { getCreatorSpace } from '@/lib/serverApi'

// Navigation is provided by CreatorStudioShell in /creator/layout.tsx.
// This layout adds content padding and — for newly opened collectives —
// the first-arrival greeting from Build Your Collective.
//
// Atlas v1.2 — the collective's Colour Palette drives the collective-scoped
// CSS custom properties (--fc-collective-*). Component adoption is
// incremental; core layout and typography remain Fresh Collective's own.
export default async function SpaceCreatorLayout({
  children, params,
}: {
  children: React.ReactNode
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params
  const space = await getCreatorSpace(slug) as
    | { colour_palette?: { key: string; name: string; palette: { primary: string; secondary: string; accent: string; background: string } } | null }
    | null
  // Pass the full palette metadata (key + name + hex slots) so the
  // client-side ``useCollectivePalette`` hook has everything it needs
  // for the picker UI, in addition to the CSS custom properties.
  const paletteMeta = space?.colour_palette ?? null

  return (
    <CollectiveThemeProvider palette={paletteMeta}>
      <div className="mx-auto max-w-6xl px-6 py-10 md:px-10">
        {children}
        <FirstArrivalOverlay slug={slug} />
      </div>
    </CollectiveThemeProvider>
  )
}
