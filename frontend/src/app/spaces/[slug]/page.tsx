import { notFound, redirect } from 'next/navigation'

import CollectiveHome from '@/components/collective/CollectiveHome'
import {
  buildPlatformArtLookup,
  getMyMemberships,
  getPublicPlatformArtwork,
  getSpace,
} from '@/lib/serverApi'
import type { SpaceMembership } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

/**
 * The Collective's front door, which answers differently depending on
 * who knocks.
 *
 * A member gets the Collective Home: an orientation hub for what they
 * can do in here. Everyone else — signed out, signed in but not a
 * member, an administrator who has never joined — gets the public
 * About page, which is the surface built to explain what this
 * Collective is and why someone might want to join it.
 *
 * Membership is the only key. An administrator is not given a member's
 * view of a Collective they do not belong to: World Management is the
 * lens for looking at a Collective from outside, and quietly widening
 * this route would put a member-only surface behind a role check
 * instead of a membership one.
 *
 * Deliberately not a ``/home`` child route. ``/spaces/{slug}`` already
 * meant "take me into this Collective" — the Collective switcher and
 * the Explore card have always pointed here, and the Explore card
 * already sends joined members here and non-members to ``/about``.
 * The branch below is that existing intent, finally rendered. A child
 * route would also be auto-protected by ``proxyRouting`` (three
 * segments), bouncing signed-out visitors to /login instead of to the
 * public page they should see.
 */
export default async function SpacePage({ params }: Props) {
  const { slug } = await params

  // Platform artwork is fetched alongside, not after: each Home tile
  // falls back to the Fresh Collective image already authored for that
  // member area, so the default Home is art-directed before a creator
  // configures anything. The call is cached and shared with the rest
  // of the request.
  const [space, memberships, artwork]: [
    Awaited<ReturnType<typeof getSpace>>,
    SpaceMembership[],
    Awaited<ReturnType<typeof getPublicPlatformArtwork>>,
  ] = await Promise.all([
    getSpace(slug),
    getMyMemberships(),
    getPublicPlatformArtwork(),
  ])

  // The layout above also 404s on a missing Collective; repeated here
  // because this page reads ``space`` before the layout's guard can
  // help it.
  if (!space) notFound()

  const isMember = memberships.some((m) => m.space_slug === slug)
  if (!isMember) redirect(`/spaces/${slug}/about`)

  return (
    <CollectiveHome
      space={space}
      platformArtwork={buildPlatformArtLookup(artwork)}
    />
  )
}
