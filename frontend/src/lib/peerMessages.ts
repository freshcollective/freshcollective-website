import type { MemberImage } from '@/types/platform'

/**
 * Client types and transport for private member-to-member
 * conversations.
 *
 * These exist only because two people both said hello — the backend
 * refuses every route with a 404 unless both directional hello rows
 * exist, and it is the persisted connection rather than current Ways to
 * Connect eligibility that authorises them. Nothing here needs to know
 * that; it is why the payload carries no shared evidence.
 */

export interface PeerParticipant {
  id: string
  display_name: string | null
  /** Resolved server-side: photo, A–Z member card, or neutral. The
   *  same resolver every other surface uses, so one person cannot
   *  appear with two different fallbacks. */
  image: MemberImage
}

export interface PeerMessageItem {
  id: string
  sender_user_id: string
  body: string
  created_at: string
  is_read: boolean
}

export interface PeerThreadSummary {
  thread_id: string
  other: PeerParticipant
  last_message: string | null
  last_message_at: string | null
  unread_count: number
}

export interface PeerThreadDetail {
  thread_id: string
  other: PeerParticipant
  messages: PeerMessageItem[]
  /** True when *the caller* set a block. One-sided on purpose: somebody
   *  who has been blocked is never told, so this is false for them and
   *  they simply find the composer unavailable. */
  blocked_by_me: boolean
  /** Whether a message may be sent right now — false while a block
   *  stands in either direction. */
  can_send: boolean
}

/** Why a member is reporting. Mirrors the backend's REPORT_CATEGORIES. */
export const REPORT_CATEGORIES = [
  { value: 'harassment_or_bullying', label: 'Harassment or bullying' },
  { value: 'hate_or_discrimination', label: 'Hate or discrimination' },
  { value: 'unsafe_behaviour', label: 'Unsafe behaviour' },
  { value: 'spam_or_scam', label: 'Spam or a scam' },
  { value: 'inappropriate_content', label: 'Inappropriate content' },
  { value: 'privacy_information', label: 'Sharing private information' },
  { value: 'misinformation', label: 'Misinformation' },
  { value: 'something_else', label: 'Something else' },
] as const

/** Send a message into an existing conversation. */
export async function sendPeerMessage(
  threadId: string,
  body: string,
): Promise<PeerMessageItem> {
  const res = await fetch(
    `/api/messages/${encodeURIComponent(threadId)}/messages`,
    {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    },
  )
  if (!res.ok) throw new Error(`send failed: ${res.status}`)
  return res.json()
}

/** Re-read a conversation, e.g. after sending. */
export async function fetchPeerThread(
  threadId: string,
): Promise<PeerThreadDetail> {
  const res = await fetch(`/api/messages/${encodeURIComponent(threadId)}`, {
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`load failed: ${res.status}`)
  return res.json()
}

/** The display name to use when somebody has none. */
export function participantName(p: PeerParticipant): string {
  return p.display_name?.trim() || 'A member'
}


/** Block the other participant. Idempotent; they are never notified. */
export async function blockPeer(threadId: string): Promise<void> {
  const res = await fetch(`/api/messages/${encodeURIComponent(threadId)}/block`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`block failed: ${res.status}`)
}

/**
 * Remove the block this member set.
 *
 * Only ever clears their own. If the other person has also blocked
 * them the conversation stays closed, which is why the caller should
 * re-read the thread rather than assume messaging has resumed.
 */
export async function unblockPeer(threadId: string): Promise<void> {
  const res = await fetch(`/api/messages/${encodeURIComponent(threadId)}/block`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`unblock failed: ${res.status}`)
}

/**
 * Report the other participant to Fresh Collective.
 *
 * Independent of blocking: reporting never blocks, and blocking never
 * reports. Returns the case number so the acknowledgement can name it.
 */
export async function reportPeer(
  threadId: string,
  category: string,
  reporterNote?: string,
): Promise<string> {
  const res = await fetch(`/api/messages/${encodeURIComponent(threadId)}/report`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category, reporter_note: reporterNote ?? null }),
  })
  if (!res.ok) throw new Error(`report failed: ${res.status}`)
  const body = (await res.json()) as { case_number: string }
  return body.case_number
}
