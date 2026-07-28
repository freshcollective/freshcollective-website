import Link from 'next/link'
import type { ActivityOut } from '@/types/platform'

/**
 * A single Recent Moments row.
 *
 * Shared across the Your-World dashboard section ("across your world")
 * and each collective's sidebar panel ("in this place"). Intentionally
 * quiet: no coloured badges, no unread dot, no "Open" button — the
 * whole row is the affordance and the click carries the reader to
 * whatever ``payload.url`` the writer set.
 *
 * Copy source:
 *   - title  ← ``activity.payload.title``, with a per-event-type
 *              fallback so the row never renders blank while writer
 *              migration is in progress.
 *   - url    ← ``activity.payload.url``; when absent the row renders
 *              as a static line rather than a link.
 */

const EVENT_FALLBACK_TITLE: Record<string, string> = {
  reply_received:            'New reply',
  mention_received:          'You were mentioned',
  private_message_received:  'New private message',
  booking_confirmed:         'Booking confirmed',
  payment_successful:        'Payment received',
  payment_failed:            'Payment issue',
  conversation_created:      'New conversation started',
  conversation_replied:      'New reply in a conversation',
  conversation_followed:     'A conversation you follow was updated',
  reaction_received:         'Someone reacted to your post',
  gathering_created:         'New gathering scheduled',
  gathering_booking:         'New booking',
  gathering_reminder:        'Gathering reminder',
  gathering_changed:         'Gathering details changed',
  gathering_cancelled:       'Gathering cancelled',
  gathering_replay_available: 'Replay is available',
  pathway_published:         'New pathway available',
  pathway_step_released:     'A new step is unlocked',
  pathway_completed:         'Pathway completed',
  pathway_comment:           'New pathway comment',
  member_joined:             'A new member joined',
  member_left:               'A member left',
  creator_announcement:      'Creator announcement',
  resource_added:            'A new resource was added',
  resource_updated:          'A resource was updated',
  subscription_started:      'Subscription started',
  subscription_renewed:      'Subscription renewed',
  subscription_cancelled:    'Subscription cancelled',
  password_changed:          'Password changed',
  creator_payout:            'Creator payout processed',
  invitation_received:       'You have a new invitation',
  invitation_accepted:       'Your invitation was accepted',
}

function titleFor(activity: ActivityOut): string {
  const t = activity.payload?.title
  if (typeof t === 'string' && t.trim().length > 0) return t
  return EVENT_FALLBACK_TITLE[activity.event_type] ?? 'Update'
}

function urlFor(activity: ActivityOut): string | null {
  const u = activity.payload?.url
  return typeof u === 'string' && u.startsWith('/') ? u : null
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Date.now() - then
  const min = 60_000
  const hour = 60 * min
  const day = 24 * hour
  if (diff < min)  return 'just now'
  if (diff < hour) return `${Math.floor(diff / min)}m ago`
  if (diff < day)  return `${Math.floor(diff / hour)}h ago`
  const d = Math.floor(diff / day)
  if (d === 1)     return 'yesterday'
  if (d < 7)       return `${d}d ago`
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

// ---------------------------------------------------------------------------
// Category icon (small, decorative)
// ---------------------------------------------------------------------------

const CATEGORY_TINT: Record<string, { bg: string; fg: string }> = {
  personal:      { bg: 'rgba(56,160,158,0.10)', fg: '#0f766e' },
  conversations: { bg: 'rgba(139,92,246,0.10)', fg: '#6d28d9' },
  gatherings:    { bg: 'rgba(212,176,72,0.14)', fg: '#7A5A00' },
  pathways:      { bg: 'rgba(56,116,180,0.10)', fg: '#1e40af' },
  collective:    { bg: 'rgba(34,197,94,0.10)',  fg: '#15803d' },
  account:       { bg: 'rgba(30,41,59,0.06)',   fg: '#334155' },
}

function CategoryIcon({ category }: { category: string }) {
  const p = {
    width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.7,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }
  switch (category) {
    case 'personal':
      return (
        <svg {...p}><path d="M11 20A7 7 0 014 13V6a1 1 0 011-1h7a7 7 0 017 7v7a1 1 0 01-1 1h-5z" /><path d="M5 19c4-3 7-6 9-11" /></svg>
      )
    case 'conversations':
      return (<svg {...p}><path d="M21 15a2 2 0 01-2 2H8l-4 4V6a2 2 0 012-2h13a2 2 0 012 2v9z" /></svg>)
    case 'gatherings':
      return (
        <svg {...p}>
          <rect x="3" y="5" width="18" height="16" rx="2" />
          <line x1="16" y1="3" x2="16" y2="7" /><line x1="8" y1="3" x2="8" y2="7" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      )
    case 'pathways':
      return (
        <svg {...p}>
          <path d="M5 20c0-4 5-6 5-10S5 6 5 2" />
          <path d="M19 20c0-4-5-6-5-10s5-4 5-8" />
        </svg>
      )
    case 'collective':
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18" />
          <path d="M12 3a13 13 0 010 18a13 13 0 010-18z" />
        </svg>
      )
    case 'account':
    default:
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19 12a7 7 0 00-.11-1.24l2.06-1.62-2-3.46-2.4.99a7 7 0 00-2.14-1.24L14 3h-4l-.41 2.43a7 7 0 00-2.14 1.24l-2.4-.99-2 3.46 2.06 1.62A7 7 0 005 12c0 .42.04.83.11 1.24l-2.06 1.62 2 3.46 2.4-.99a7 7 0 002.14 1.24L10 21h4l.41-2.43a7 7 0 002.14-1.24l2.4.99 2-3.46-2.06-1.62c.07-.41.11-.82.11-1.24z" />
        </svg>
      )
  }
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

interface Props {
  activity: ActivityOut
  /** ``comfortable`` = dashboard density (small icon well + timestamp row).
   *  ``compact`` = sidebar density (icon flush with title, single line). */
  variant?: 'comfortable' | 'compact'
}

export default function RecentMomentsRow({ activity, variant = 'comfortable' }: Props) {
  const tint = CATEGORY_TINT[activity.category] ?? CATEGORY_TINT.account
  const title = titleFor(activity)
  const url = urlFor(activity)
  const time = relativeTime(activity.created_at)

  const body = variant === 'compact' ? (
    <div className="flex items-baseline gap-2">
      <span
        className="mt-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded"
        style={{ background: tint.bg, color: tint.fg }}
      >
        <CategoryIcon category={activity.category} />
      </span>
      <span className="min-w-0 flex-1 truncate text-[12.5px] leading-snug text-navy-900">
        {title}
      </span>
      <span className="shrink-0 text-[11px] text-slate-500">{time}</span>
    </div>
  ) : (
    <div className="flex items-start gap-3">
      <span
        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
        style={{ background: tint.bg, color: tint.fg }}
        aria-hidden="true"
      >
        <CategoryIcon category={activity.category} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[14px] leading-snug text-navy-900">{title}</p>
        <p className="mt-0.5 text-[12px] text-slate-500">{time}</p>
      </div>
    </div>
  )

  if (url) {
    return (
      <Link
        href={url}
        className="block rounded-lg px-2 py-1.5 transition-colors hover:bg-slate-50"
      >
        {body}
      </Link>
    )
  }
  return <div className="px-2 py-1.5">{body}</div>
}
