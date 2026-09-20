/**
 * Which tiles the member Collective Home shows, and what each says.
 *
 * Pure data, deliberately kept out of the component: the rules here —
 * that a real member area survives an empty week, that zero is stated
 * rather than hidden — are product decisions worth testing directly,
 * and a ``.tsx`` module cannot be imported by the test runner.
 */

import type { SpaceResponse } from '@/types/platform'

const TILE_COPY = {
  gatherings: 'Sessions, events and ways to come together.',
  pathways: 'Courses, programs and guided experiences.',
  conversations: 'See what members are sharing, asking and exploring together.',
  members: 'Meet the people who are part of this Collective.',
  about: 'The story, purpose and people behind this Collective.',
} as const

interface Tile {
  key: keyof typeof TILE_COPY
  name: string
  href: string
  description: string
  /** Small live signal, or null when there is nothing worth saying. */
  meta: string | null
  cta: string
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

/** "No upcoming gatherings" / "12 upcoming · next 5 Oct".
 *
 *  Zero is stated rather than hidden. A member between terms should
 *  read a calm fact, not meet an empty space where a number was. */
function gatheringsMeta(space: SpaceResponse): string {
  const count = space.upcoming_gathering_count ?? 0
  if (count === 0) return 'No upcoming gatherings'

  const parts = [`${count} upcoming`]
  if (space.next_gathering_starts_at) {
    parts.push(
      `next ${new Date(space.next_gathering_starts_at).toLocaleDateString(undefined, {
        day: 'numeric',
        month: 'short',
      })}`,
    )
  }
  return parts.join(' · ')
}

function pathwaysMeta(space: SpaceResponse): string {
  const count = space.pathways?.length ?? 0
  return count === 0
    ? 'No pathways available yet'
    : `${plural(count, 'pathway', 'pathways')} available`
}

function membersMeta(space: SpaceResponse): string | null {
  const total = (space.learner_count ?? 0) + (space.leader_count ?? 0)
  return total > 0 ? plural(total, 'member', 'members') : null
}

export function buildTiles(space: SpaceResponse): Tile[] {
  const base = `/spaces/${space.slug}`
  const tiles: Tile[] = [
    {
      key: 'gatherings',
      name: 'Gatherings',
      href: `${base}/events`,
      description: TILE_COPY.gatherings,
      meta: gatheringsMeta(space),
      cta: 'View gatherings →',
    },
    {
      key: 'pathways',
      name: 'Pathways',
      href: `${base}/pathways`,
      description: TILE_COPY.pathways,
      meta: pathwaysMeta(space),
      cta: 'View pathways →',
    },
    {
      key: 'conversations',
      name: 'Conversations',
      href: `${base}/community`,
      // No metric in v1: a raw post count is vanity, and an unread
      // count would need per-member read state that does not exist.
      // Better an honest description than a misleading number.
      description: TILE_COPY.conversations,
      meta: null,
      cta: 'Join the conversation →',
    },
  ]

  // The one tile a Collective can genuinely switch off. Everything
  // else above is a permanent member area.
  if (space.show_member_directory) {
    tiles.push({
      key: 'members',
      name: 'Members',
      href: `${base}/members`,
      description: TILE_COPY.members,
      meta: membersMeta(space),
      cta: 'Meet the members →',
    })
  }

  tiles.push({
    key: 'about',
    name: 'About',
    href: `${base}/about`,
    description: TILE_COPY.about,
    meta: null,
    cta: 'Read more →',
  })

  return tiles
}
