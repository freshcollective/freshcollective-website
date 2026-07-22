/**
 * Shared vocabulary for Gatherings — mirrors
 * `backend/app/services/gathering_types.py`. Every visible surface
 * (creator form, member cards, detail page) reads from these
 * arrays so adding a type is a single-line change on each side.
 *
 * Icons are strictly type-driven. Creators pick a type; the platform
 * chooses the icon.
 */

// -----------------------------------------------------------------------------
// Gathering Type
// -----------------------------------------------------------------------------

export interface GatheringType {
  value: string
  label: string
  icon: string
  /** Short, warm sentence describing what this type feels like.
   *  Shown under the type dropdown in the creator form and in any
   *  contextual UI that benefits from a small caption. */
  description: string
}

export const GATHERING_TYPES: readonly GatheringType[] = [
  { value: 'circle',        label: 'Circle',           icon: '⭕',  description: 'Reflect together in an open, supportive space.' },
  { value: 'conversation',  label: 'Conversation',     icon: '💬',  description: 'Explore an idea together.' },
  { value: 'workshop',      label: 'Workshop',         icon: '🛠️', description: 'Learn through guided practice.' },
  { value: 'retreat',       label: 'Retreat',          icon: '🌿',  description: 'Step away from everyday life for deeper restoration.' },
  { value: 'celebration',   label: 'Celebration',      icon: '✨',  description: 'Mark a shared milestone together.' },
  { value: 'practice',      label: 'Practice',         icon: '🧘',  description: 'Move, breathe or meditate together.' },
  { value: 'live_online',   label: 'Live Online',      icon: '💻',  description: 'Come together over video.' },
  { value: 'walk',          label: 'Walk',             icon: '🚶',  description: 'Slow, moving conversation shared side by side.' },
  { value: 'coffee_chat',   label: 'Coffee Chat',      icon: '☕',  description: 'Relaxed conversation and connection.' },
  { value: 'book_club',     label: 'Book Club',        icon: '📚',  description: 'Read together and share what you\u2019re noticing.' },
  { value: 'qa',            label: 'Q&A',              icon: '❓',  description: 'Ask questions and receive thoughtful answers.' },
  { value: 'creative',      label: 'Creative Session', icon: '🎨',  description: 'Make something together in a shared session.' },
  { value: 'shared_meal',   label: 'Shared Meal',      icon: '🍽️', description: 'Gather around a table and share a meal.' },
  { value: 'other',         label: 'Other',            icon: '📅',  description: 'A moment for people to come together.' },
] as const

const TYPE_LOOKUP: Record<string, GatheringType> = Object.fromEntries(
  GATHERING_TYPES.map((t) => [t.value, t]),
)

export function gatheringIcon(value: string | null | undefined): string {
  return (TYPE_LOOKUP[value ?? 'other'] ?? TYPE_LOOKUP['other']).icon
}

export function gatheringLabel(value: string | null | undefined): string {
  return (TYPE_LOOKUP[value ?? 'other'] ?? TYPE_LOOKUP['other']).label
}

export function gatheringDescription(value: string | null | undefined): string {
  return (TYPE_LOOKUP[value ?? 'other'] ?? TYPE_LOOKUP['other']).description
}

// -----------------------------------------------------------------------------
// Attendance Format
// -----------------------------------------------------------------------------

export interface AttendanceFormat {
  value: 'online' | 'in_person' | 'hybrid'
  label: string
}

export const ATTENDANCE_FORMATS: readonly AttendanceFormat[] = [
  { value: 'online',    label: 'Online' },
  { value: 'in_person', label: 'In person' },
  { value: 'hybrid',    label: 'Hybrid' },
] as const

const FORMAT_LOOKUP: Record<string, AttendanceFormat> = Object.fromEntries(
  ATTENDANCE_FORMATS.map((f) => [f.value, f]),
)

export function attendanceFormatLabel(value: string | null | undefined): string {
  return (FORMAT_LOOKUP[value ?? 'online'] ?? FORMAT_LOOKUP['online']).label
}

// -----------------------------------------------------------------------------
// Access Type
// -----------------------------------------------------------------------------

export type AccessTypeValue =
  | 'free'
  | 'included_with_collective'
  | 'included_with_pathway'
  | 'paid_separately'
  | 'invitation_only'

export interface AccessType {
  value: AccessTypeValue
  label: string
  /** Short chip-friendly label for cards. */
  short: string
  /** True when the current phase supports in-app booking for this
   *  access type. `paid_separately` and `invitation_only` are
   *  first-class data concepts but their flows are follow-ups. */
  bookable: boolean
}

export const ACCESS_TYPES: readonly AccessType[] = [
  { value: 'free',                      label: 'Free',                                  short: 'Free',        bookable: true  },
  { value: 'included_with_collective',  label: 'Included with Collective membership',   short: 'Included',    bookable: true  },
  { value: 'included_with_pathway',     label: 'Included with a Pathway',               short: 'With Pathway',bookable: true  },
  { value: 'paid_separately',           label: 'Paid separately',                       short: 'Ticketed',    bookable: false },
  { value: 'invitation_only',           label: 'Invitation only',                       short: 'Invite only', bookable: false },
] as const

const ACCESS_LOOKUP: Record<string, AccessType> = Object.fromEntries(
  ACCESS_TYPES.map((a) => [a.value, a]),
)

/** Map any legacy or unknown value to the current vocabulary. */
export function normaliseAccessType(value: string | null | undefined): AccessTypeValue {
  if (!value) return 'included_with_collective'
  if (value in ACCESS_LOOKUP) return value as AccessTypeValue
  if (value === 'all_members') return 'included_with_collective'
  if (value === 'pathway_required') return 'included_with_pathway'
  return 'included_with_collective'
}

export function accessTypeMeta(value: string | null | undefined): AccessType {
  return ACCESS_LOOKUP[normaliseAccessType(value)]
}
