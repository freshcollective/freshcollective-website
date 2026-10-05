/**
 * The member navigation list, and which item is active.
 *
 * Extracted from ``WorldHeader.tsx`` so it can be tested by running it
 * rather than by reading it. The Node test runner strips types but not
 * JSX, so anything living in a ``.tsx`` file can only be asserted on as
 * source text — which is how the previous navigation suite had to work,
 * and why it could check that a flag was *mentioned* on the right line
 * but never that the list came out right.
 */

// Relative, with the extension: a *value* import of a sibling, and the
// node test runner resolves ESM without the `@/` alias. Same pattern as
// collectiveHomeArtwork.ts and payoutSetupCard.ts.
import { CREATOR_STUDIO_HREF } from './creatorStudioAccess.ts'

export interface NavItem {
  href: string
  label: string
}

export interface NavAudience {
  /** Mirrors the backend's discovery_pillar_enabled flag. */
  discoveryOn: boolean
  waysToConnectOn: boolean
  /** From ``canAccessCreatorStudio`` — never a role or plan check here. */
  creatorStudioOn: boolean
}

/**
 * Peer destinations in the pillar order defined by
 * docs/foundations/discovery-connection-belonging-v1.1.md.
 * Your World is always first for signed-in visitors.
 *
 * Creator Studio goes last of the list, which puts it after Messages
 * and before the notification bell on desktop and before Notifications
 * in the drawer — the member destinations stay together and the
 * creator-facing doorway sits at the end of them rather than in the
 * middle.
 */
export function memberNavItems(audience: NavAudience): NavItem[] {
  // Destructured, and each entry kept on one line, because three
  // existing suites assert on the shape of these lines —
  // peerMessages, waysToConnectOptIn and navigationFlags each pin
  // "this destination is gated on that flag and no other". They were
  // written that way because the gating is textual and was duplicated
  // across four nav surfaces. Moving the list did not make those
  // guarantees less worth keeping, so the formatting carries over with
  // it rather than three tests being rewritten around a refactor.
  const { discoveryOn, waysToConnectOn, creatorStudioOn } = audience
  const items: NavItem[] = [
    { href: '/dashboard', label: 'Your World' },
    { href: '/spaces',    label: 'Explore Collectives' },
  ]
  // One flag each — see lib/featureFlags.ts.
  if (discoveryOn) items.push({ href: '/discover-places', label: 'Discover Places' })
  if (waysToConnectOn) items.push({ href: '/ways-to-connect', label: 'Ways to Connect' })
  // Messages rides the same flag rather than getting one of its own: a
  // private conversation can only come into existence through a mutual
  // hello, so with Ways to Connect off there is nothing for this
  // destination to show. One flag, one feature.
  if (waysToConnectOn) items.push({ href: '/messages', label: 'Messages' })
  // Not a pillar and not flagged: the doorway follows access, so a
  // creator keeps it with both pillar flags off and a member never
  // gains it with both on.
  if (creatorStudioOn) items.push({ href: CREATOR_STUDIO_HREF, label: 'Creator Studio' })
  return items
}

/**
 * A nav item is "active" when its href matches the pathname exactly, or
 * when a nested page under that destination is being viewed.
 *
 * Creator Studio is matched on its own prefix and nothing else. Two
 * near-misses worth being deliberate about:
 *
 *   * ``/spaces/{slug}`` — a creator looking at a Collective they built
 *     is on a *member* surface. Explore Collectives lights up, not
 *     Creator Studio.
 *   * ``/creator/...`` — the legacy route that renders the same shell.
 *     It is a different prefix, and ``startsWith('/creator-studio/')``
 *     does not match it. A looser ``startsWith('/creator')`` would mark
 *     Creator Studio active there, which happens to be *almost* right
 *     and is the kind of coincidence that stops being true later.
 */
export function isNavItemActive(pathname: string, href: string): boolean {
  if (pathname === href) return true
  if (href === '/spaces' && pathname.startsWith('/spaces/')) return true
  if (href === '/discover-places' && pathname.startsWith('/discover-places/')) return true
  if (href === '/ways-to-connect' && pathname.startsWith('/ways-to-connect/')) return true
  if (href === '/dashboard' && pathname.startsWith('/dashboard/')) return true
  if (href === CREATOR_STUDIO_HREF && pathname.startsWith(`${CREATOR_STUDIO_HREF}/`)) return true
  return false
}
