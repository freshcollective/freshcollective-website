import { notFound } from 'next/navigation'
import SpaceNav from '@/components/spaces/SpaceNav'
import CollectiveSwitcher from '@/components/spaces/CollectiveSwitcher'
import CollectiveThemeProvider from '@/components/collective/CollectiveThemeProvider'
import CollectiveIdentityHeader from '@/components/spaces/CollectiveIdentityHeader'
import SiteShell from '@/components/layout/SiteShell'
import { getSpace, getMe, getMyMemberships, getSpaceMessageThreads, getUnseenCounts } from '@/lib/serverApi'
import { unseenForCollective } from '@/lib/unseenForCollective'
import type { SpaceMembership, UserProfile } from '@/types/platform'

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

  // Unread count for the Messages badge. Genuinely non-critical — a
  // missing badge is not worth an error page — so a failure is ignored
  // *here* on purpose. That is the one place the old swallow-everything
  // pattern was right, and it now says so instead of looking like the
  // pages that were wrong.
  //
  // Shares the request with the messages page below it: ``cache()`` dedupes
  // within a request, so this no longer costs a second round trip, and
  // there is one place that knows how to read this endpoint.
  let unreadMessageCount = 0
  if (isMember) {
    const inbox = await getSpaceMessageThreads(slug)
    if (inbox.kind === 'ok') {
      unreadMessageCount = inbox.data.reduce((sum, t) => sum + t.unread_count, 0)
    }
  }

  // Unseen activity for the three member tabs. Same posture as the
  // Messages count above: non-critical, and ``cache()``-deduped with
  // the section pages, which read the same response for the boundary
  // they report back.
  let unseenByCategory: Record<string, number> | undefined
  if (isMember) {
    // Unscoped so the layout, all three section pages and the
    // Collective Home share a single cache()'d request per page load.
    unseenByCategory = unseenForCollective(await getUnseenCounts(), space.id)
  }

  // Atlas v1.2 — the chosen Colour Palette drives collective-scoped CSS
  // custom properties (--fc-collective-*, --fc-accent, --fc-accent-soft,
  // --fc-accent-line) *and* the ``useCollectivePalette`` React context
  // consumed by the shared colour picker. Passing the full metadata
  // (key + name + hex slots) hydrates both layers from one prop.
  const paletteMeta = space.colour_palette ?? null

  return (
    <CollectiveThemeProvider palette={paletteMeta}>
    <SiteShell noFooter>
    <div className="flex min-h-screen flex-col" style={{ background: '#FAFAF8' }}>

      {/* ── Collective context band ────────────────────────────────
          The persistent member navigation (wordmark, Your World,
          Explore Collectives, Discover Places, Ways to Connect,
          notifications, profile, log out) is provided by SiteShell
          above — auth-aware, so authenticated members see WorldHeader
          and signed-out visitors browsing the About page see the
          public header. What remains here is the *inside-Collective*
          context: the switcher between collectives the member
          belongs to. */}
      <div
        className="border-b border-border bg-surface py-3"
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
        </div>
      </div>

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

      <SpaceNav
        spaceSlug={slug}
        spaceName={space.name}
        isMember={isMember}
        unreadMessageCount={unreadMessageCount}
        unseenByCategory={unseenByCategory}
        showMemberDirectory={space.show_member_directory ?? true}
        reachableAreas={space.area_access}
      />

      <div className="flex-1 py-10 pb-24 md:pb-10">
        <div className="mx-auto max-w-6xl px-6 md:px-10">
          {children}
        </div>
      </div>
    </div>
    </SiteShell>
    </CollectiveThemeProvider>
  )
}
