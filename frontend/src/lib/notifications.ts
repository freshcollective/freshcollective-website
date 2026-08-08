/**
 * Notification presentation helpers.
 *
 * Single source of truth for how a raw `notification_type` string
 * becomes something a member should see and where clicking should
 * send them. Consumers (NotificationBell, notifications page) should
 * never render `notification_type` directly — always through
 * `notificationLabel()` so internal identifiers like
 * `creator_plan_granted_by_stripe` never leak to the UI.
 */

import type { NotificationItem } from '@/types/platform'

// ── Category ────────────────────────────────────────────────────────────
// A grouping used for icon + tint. Notifications with a similar visual
// treatment (conversations, gatherings, plan/account, etc.) share a
// category. Anything unrecognised falls back to 'update' — a neutral
// category that never surfaces a raw type string.
export type NotificationCategory =
  | 'conversation'
  | 'gathering'
  | 'pathway'
  | 'community'
  | 'plan'
  | 'message'
  | 'moderation'
  | 'update'

// ── Presentation tokens ─────────────────────────────────────────────────
// Warmer than the raw slate scheme — reads as belonging to the Fresh
// Collective world rather than a generic notification tray.
const TINT: Record<NotificationCategory, { bg: string; fg: string; label: string; icon: string }> = {
  conversation: { bg: 'rgba(56, 160, 158, 0.12)', fg: '#0f766e', label: 'Conversation',    icon: '💬' },
  gathering:    { bg: 'rgba(212, 176, 72, 0.16)', fg: '#8a6a1f', label: 'Gathering',       icon: '📅' },
  pathway:      { bg: 'rgba(94, 63, 145, 0.12)',  fg: '#5C4577', label: 'Pathway',         icon: '🧭' },
  community:    { bg: 'rgba(16, 185, 129, 0.14)', fg: '#0f6b46', label: 'Community',       icon: '🤝' },
  plan:         { bg: 'rgba(56, 160, 158, 0.12)', fg: '#0f766e', label: 'Plan',            icon: '✦' },
  message:      { bg: 'rgba(56, 160, 158, 0.12)', fg: '#0f766e', label: 'Message',         icon: '✉' },
  moderation:   { bg: 'rgba(12, 24, 38, 0.06)',   fg: 'rgba(12,24,38,0.72)', label: 'Community Care', icon: '⚖' },
  update:       { bg: 'rgba(12, 24, 38, 0.06)',   fg: 'rgba(12,24,38,0.72)', label: 'Update',         icon: '•' },
}

// ── Per-type mapping ────────────────────────────────────────────────────
// The label here is the *category* label shown on the badge (short,
// scannable). Longer, per-event copy lives in the notification's
// title/message and comes from the backend.
type TypeMeta = { category: NotificationCategory; label?: string }

const TYPE_MAP: Record<string, TypeMeta> = {
  // Conversations
  comment_reply:   { category: 'conversation', label: 'Reply' },
  new_post:        { category: 'conversation', label: 'Conversation' },
  mention:         { category: 'conversation', label: 'Mention' },
  caretaker_answer:{ category: 'conversation', label: 'Answer' },

  // Gatherings
  event_reminder:      { category: 'gathering', label: 'Reminder' },
  event_registration:  { category: 'gathering', label: 'Booking' },
  booking_confirmed:   { category: 'gathering', label: 'Booking' },
  gathering_cancelled: { category: 'gathering', label: 'Cancelled' },

  // Pathways
  new_pathway:                     { category: 'pathway', label: 'New pathway' },
  new_pathway_step:                { category: 'pathway', label: 'New step' },
  pathway_completed:               { category: 'pathway', label: 'Completed' },
  pathway_access_granted_by_platform: { category: 'pathway', label: 'Access granted' },

  // Community
  new_member: { category: 'community', label: 'New member' },

  // Plan / account — never expose the "_by_stripe" / "_by_platform" split.
  creator_plan_granted_by_stripe:   { category: 'plan', label: 'Plan activated' },
  creator_plan_granted_by_platform: { category: 'plan', label: 'Plan activated' },

  // Broadcasts / announcements
  admin_broadcast: { category: 'update', label: 'Announcement' },

  // Direct messages
  direct_message: { category: 'message', label: 'Message' },
}

// Community Care events are a family; match by prefix so we don't have
// to enumerate every kind. They're audit notifications, so a single
// "Community Care" label is right.
function communityCareMeta(type: string): TypeMeta | null {
  if (type.startsWith('community_care_')) {
    return { category: 'moderation', label: 'Community Care' }
  }
  return null
}

function metaFor(type: string): TypeMeta {
  return TYPE_MAP[type] ?? communityCareMeta(type) ?? { category: 'update', label: 'Update' }
}

// ── Public API ──────────────────────────────────────────────────────────

/** Human category tint tokens (background + foreground + emoji). */
export function notificationTint(type: string): { bg: string; fg: string; icon: string } {
  const { category } = metaFor(type)
  const t = TINT[category]
  return { bg: t.bg, fg: t.fg, icon: t.icon }
}

/** Short category label for the badge. Never returns the raw type. */
export function notificationLabel(type: string): string {
  const meta = metaFor(type)
  return meta.label ?? TINT[meta.category].label
}

/**
 * Resolve where clicking a notification should navigate. Prefer the
 * backend-supplied URL; fall back to a sensible destination for the
 * category so the click is always meaningful (never a dead link).
 */
export function notificationDestination(notif: NotificationItem): string {
  if (notif.url && notif.url.trim().length > 0) return notif.url
  const { category } = metaFor(notif.notification_type)
  switch (category) {
    case 'plan':       return '/creator-studio'
    case 'gathering':  return '/dashboard'
    case 'pathway':    return '/dashboard'
    case 'community':  return '/dashboard'
    case 'conversation': return '/dashboard'
    case 'message':    return '/dashboard'
    case 'moderation': return '/notifications'
    case 'update':     return '/notifications'
  }
}

/**
 * Fire the mark-as-read side effect for a notification click. Kept
 * separate from navigation so the caller can choose *how* to
 * navigate (Link click, router.push, etc.) — both the dropdown and
 * the full-page notification row funnel through this so the read
 * marker is guaranteed to fire before navigation regardless of
 * surface.
 *
 * Never throws — a mark-read failure must not block navigation.
 */
export async function markNotificationRead(notificationId: string): Promise<void> {
  const { apiUrl } = await import('@/lib/api')
  try {
    await fetch(apiUrl(`/api/notifications/${notificationId}/read`), {
      method: 'POST',
      credentials: 'include',
    })
  } catch {
    // Non-critical — navigation must proceed regardless.
  }
}

/**
 * Warmer relative time — same shape as the previous helpers but with
 * a graceful degrade to an absolute date for anything older than a
 * week. Kept close to spoken English.
 */
export function notificationRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  const diffHr = Math.floor(diffMs / 3_600_000)
  const diffDay = Math.floor(diffMs / 86_400_000)
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin} min ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDay === 1) return 'Yesterday'
  if (diffDay < 7) return `${diffDay}d ago`
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
