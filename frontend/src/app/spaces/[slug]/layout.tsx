import { notFound } from 'next/navigation'
import Link from 'next/link'
import { cookies } from 'next/headers'
import SpaceNav from '@/components/spaces/SpaceNav'
import CollectiveSwitcher from '@/components/spaces/CollectiveSwitcher'
import CollectiveThemeProvider from '@/components/collective/CollectiveThemeProvider'
import CollectiveIdentityHeader from '@/components/spaces/CollectiveIdentityHeader'
import { getSpace, getMe, getMyMemberships } from '@/lib/serverApi'
import { apiUrl } from '@/lib/api'
import { SESSION_COOKIE } from '@/lib/session'
import type { MessageThreadSummary, SpaceMembership, UserProfile } from '@/types/platform'

interface Props {
  children: React.ReactNode
  params: Promise<{ slug: string }>
}

export default async function SpaceLayout({ children, params }: Props) {
  const { slug } = await params

  const [space, user, memberships]: [
    Awaited<ReturnType<typeof getSpace>>,
    UserProfile | null,
    SpaceMembership[],
  ] = await Promise.all([getSpace(slug), getMe(), getMyMemberships()])

  if (!space) notFound()

  const isMember = memberships.some((m) => m.space_slug === slug)

  // Fetch unread message count for badge (silently ignore errors)
  let unreadMessageCount = 0
  if (isMember) {
    try {
      const cookieStore = await cookies()
      const token = cookieStore.get(SESSION_COOKIE)?.value ?? ''
      const msgRes = await fetch(apiUrl(`/api/spaces/${slug}/messages`), {
        headers: { Cookie: `${SESSION_COOKIE}=${token}` },
        cache: 'no-store',
      })
      if (msgRes.ok) {
        const threads: MessageThreadSummary[] = await msgRes.json()
        unreadMessageCount = threads.reduce((sum, t) => sum + t.unread_count, 0)
      }
    } catch { /* non-critical */ }
  }

  // Atlas v1.2 — the chosen Colour Palette drives collective-scoped CSS
  // custom properties (--fc-collective-*, --fc-accent, --fc-accent-soft,
  // --fc-accent-line) *and* the ``useCollectivePalette`` React context
  // consumed by the shared colour picker. Passing the full metadata
  // (key + name + hex slots) hydrates both layers from one prop.
  const paletteMeta = space.colour_palette ?? null

  return (
    <CollectiveThemeProvider palette={paletteMeta}>
    <div className="flex min-h-screen flex-col" style={{ background: '#FAFAF8' }}>

      {/* ── Top navigation bar ── */}
      <header
        className="border-b border-border bg-surface py-3.5"
        style={{ borderTop: '2px solid var(--fc-accent, #38A09E)' }}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 md:px-10">
          <CollectiveSwitcher
            memberships={memberships}
            currentSlug={slug}
            currentName={space.name}
            userRole={user?.role ?? 'learner'}
            isAuthenticated={!!user}
          />
          <div className="flex items-center gap-4">
            {user ? (
              <>
                <Link href="/settings" className="text-sm text-black transition-colors hover:text-navy-700">
                  Settings
                </Link>
                <Link href="/dashboard" className="text-sm text-black transition-colors hover:text-navy-700">
                  ← Your World
                </Link>
              </>
            ) : (
              <Link
                href="/login"
                className="rounded-full px-4 py-1.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                Log in
              </Link>
            )}
          </div>
        </div>
      </header>

      {/* ── Collective identity band (Atlas v1.2) ────────────────
          Location artwork is the primary visual identity. Falls back
          to the previous cover_image_url behaviour for legacy spaces
          with no Location assigned. See CollectiveIdentityHeader. */}
      <CollectiveIdentityHeader
        collectiveName={space.name}
        tagline={space.tagline}
        logoUrl={space.logo_url}
        coverImageUrl={space.cover_image_url}
        location={space.location ?? null}
        atmosphereLabels={space.atmosphere_labels ?? []}
      />

      <SpaceNav spaceSlug={slug} spaceName={space.name} isMember={isMember} unreadMessageCount={unreadMessageCount} />

      <main className="flex-1 py-10 pb-24 md:pb-10">
        <div className="mx-auto max-w-6xl px-6 md:px-10">
          {children}
        </div>
      </main>
    </div>
    </CollectiveThemeProvider>
  )
}
