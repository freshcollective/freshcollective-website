/**
 * Which tiles the member Collective Home shows, and what each says.
 *
 * Pure data, deliberately kept out of the component: the rules here
 * are product decisions worth testing directly, and a ``.tsx`` module
 * cannot be imported by the test runner.
 *
 * Order and visibility are decided by the **server**, which hands back
 * ``home_tiles`` already resolved — creator configuration laid over
 * the platform defaults, with anything a privacy setting forbids
 * removed. That placement is deliberate: if the client decided
 * visibility, a creator's configuration could expose a member
 * directory the Collective had switched off. This module only turns
 * that resolved list into render-ready copy and links.
 *
 * When ``home_tiles`` is absent — an older payload, a failed fetch —
 * the canonical default order is used, so the Home degrades to Phase 1
 * behaviour rather than to an empty page.
 */

import type { SpaceResponse } from '@/types/platform'

/** Platform copy, used whenever a creator has not written their own. */
export const HOME_TILE_DEFAULT_COPY = {
  gatherings: 'Sessions, events and ways to come together.',
  pathways: 'Courses, programs and guided experiences.',
  conversations: 'See what members are sharing, asking and exploring together.',
  // Deliberately not "connect with people in your Collective". A
  // thread is keyed (space, creator, member) and the member endpoint
  // filters to the caller's own threads, so this is a private line to
  // whoever runs the Collective — not member-to-member messaging. The
  // copy says what the feature does.
  messages: 'Talk privately with the people running this Collective.',
  members: 'Meet the people who are part of this Collective.',
  about: 'The story, purpose and people behind this Collective.',
} as const

export type TileKey = keyof typeof HOME_TILE_DEFAULT_COPY

/** Mirrors MAX_DESCRIPTION_LENGTH in app/spaces/home_config.py. */
export const MAX_HOME_DESCRIPTION = 160

export const HOME_TILE_LABEL: Record<TileKey, string> = {
  gatherings: 'Gatherings',
  pathways: 'Pathways',
  conversations: 'Conversations',
  messages: 'Messages',
  members: 'Members',
  about: 'About',
}

const TILE_PATH: Record<TileKey, string> = {
  gatherings: 'events',
  pathways: 'pathways',
  conversations: 'community',
  messages: 'messages',
  members: 'members',
  about: 'about',
}

const TILE_CTA: Record<TileKey, string> = {
  gatherings: 'View gatherings →',
  pathways: 'View pathways →',
  conversations: 'Join the conversation →',
  messages: 'Open messages →',
  members: 'Meet the members →',
  about: 'Read more →',
}

/** Canonical order, used when the server sent no resolved list. */
export const DEFAULT_TILE_ORDER: TileKey[] = [
  'gatherings', 'pathways', 'conversations', 'messages', 'members', 'about',
]

export interface Tile {
  key: TileKey
  name: string
  href: string
  description: string
  /** Small live signal, or null when there is nothing worth saying. */
  meta: string | null
  cta: string
  /** Creator-chosen image, or null to fall back. */
  imageUrl: string | null
}

export interface ResolvedTileConfig {
  key: string
  image_url?: string | null
  description?: string | null
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

function metaFor(key: TileKey, space: SpaceResponse): string | null {
  if (key === 'gatherings') return gatheringsMeta(space)
  if (key === 'pathways') return pathwaysMeta(space)
  if (key === 'members') return membersMeta(space)
  // Conversations: a post count is vanity and an unread count would
  // need read-state that does not exist.
  // Messages: an unread count IS available, but only from a second
  // request this page does not otherwise make. Neither gets a number
  // it cannot stand behind.
  return null
}

export function buildTiles(space: SpaceResponse): Tile[] {
  const base = `/spaces/${space.slug}`

  const resolved: ResolvedTileConfig[] =
    space.home_tiles && space.home_tiles.length > 0
      ? space.home_tiles
      : DEFAULT_TILE_ORDER.map((key) => ({ key }))

  return resolved
    .filter((entry): entry is ResolvedTileConfig & { key: TileKey } =>
      (entry.key as TileKey) in HOME_TILE_DEFAULT_COPY)
    // The server already enforces this; repeating it here means an
    // older or cached payload with no `home_tiles` can never surface a
    // directory the Collective has switched off.
    .filter((entry) => entry.key !== 'members' || space.show_member_directory !== false)
    .map((entry) => ({
      key: entry.key,
      name: HOME_TILE_LABEL[entry.key],
      href: `${base}/${TILE_PATH[entry.key]}`,
      // A creator's words replace the platform's for that tile only.
      description: entry.description || HOME_TILE_DEFAULT_COPY[entry.key],
      meta: metaFor(entry.key, space),
      cta: TILE_CTA[entry.key],
      imageUrl: entry.image_url || null,
    }))
}
