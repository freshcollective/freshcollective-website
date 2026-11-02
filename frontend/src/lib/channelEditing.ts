/**
 * The decisions the channel editor makes before it sends a PATCH.
 *
 * Extracted from the component because the mistakes here are quiet
 * ones: sending the wrong `channel_type`, or sending
 * `linked_experiences` when it should have been omitted — which tells
 * the backend to replace the links, so editing a name would unlink
 * everything. None of that is visible in the rendered output, so
 * testing the component would not catch it.
 */

export type Arrangement = 'open' | 'private' | 'linked'

export type ChannelType =
  | 'open'
  | 'private'
  | 'pathway'
  | 'gathering'
  | 'series'
  | 'general'
  | 'start_here'

export interface ExperienceRef {
  type: 'pathway' | 'gathering' | 'series'
  id: string
}

const LINKED_TYPES: ChannelType[] = ['pathway', 'gathering', 'series']

/** How a stored channel reads back to the creator. */
export function arrangementOf(channelType: string): Arrangement {
  if (LINKED_TYPES.includes(channelType as ChannelType)) return 'linked'
  if (channelType === 'private') return 'private'
  return 'open'
}

/**
 * The stored type for an arrangement.
 *
 * A linked channel takes the kind of its first selected experience,
 * because the backend keeps the pathway/gathering/series vocabulary
 * for icons and the page's grouping headings. `gathering` is the
 * fallback when nothing is selected yet — the backend refuses a linked
 * channel with no links, so that request fails cleanly rather than
 * being stored wrong.
 */
export function storedChannelType(
  arrangement: Arrangement,
  links: ExperienceRef[],
): ChannelType {
  if (arrangement !== 'linked') return arrangement
  return links[0]?.type ?? 'gathering'
}

/**
 * Whether a change lets more people read what is already in the
 * channel.
 *
 * Only widening needs a warning. Narrowing exposes nobody, and moving
 * between linked kinds is sideways.
 */
export function broadensAccess(from: Arrangement, to: Arrangement): boolean {
  const breadth: Record<Arrangement, number> = {
    private: 0,
    linked: 1,
    open: 2,
  }
  return breadth[to] > breadth[from]
}

export interface ChannelEditInput {
  name: string
  description: string
  memberPostingAllowed: boolean
  pollsAllowed: boolean
  arrangement: Arrangement
  currentChannelType: string
  links: ExperienceRef[]
  /** Common Room: only name and description may change. */
  systemGeneral?: boolean
}

/**
 * The PATCH body for an edit.
 *
 * `linked_experiences` is present only when the channel is, or is
 * becoming, linked. Its absence is meaningful to the backend — it
 * means "leave the links alone" — so sending an empty array from an
 * open channel's rename would unlink everything it had.
 */
export function buildChannelEditPatch(
  input: ChannelEditInput,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {
    name: input.name.trim(),
    description: input.description.trim() || null,
  }
  if (input.systemGeneral) return patch

  patch.member_posting_allowed = input.memberPostingAllowed
  patch.polls_allowed = input.pollsAllowed

  const current = arrangementOf(input.currentChannelType)
  if (input.arrangement !== current) {
    patch.channel_type = storedChannelType(input.arrangement, input.links)
  }
  if (input.arrangement === 'linked') {
    patch.linked_experiences = input.links
  }
  return patch
}
