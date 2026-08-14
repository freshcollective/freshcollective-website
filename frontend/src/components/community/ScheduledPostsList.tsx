'use client'

import { useCallback, useMemo, useState } from 'react'
import { apiUrl } from '@/lib/api'
import PostTypeTag from './PostTypeTag'

/**
 * ScheduledPostsList — the Queue timeline. Renders every scheduled
 * conversation grouped by publication date (Today / Tomorrow /
 * "Friday 24 July"). Each row is calm and editorial rather than card-
 * dense; the actions live in a small overflow menu so a busy caretaker
 * can scan the whole day at a glance.
 *
 * Data flows in from CommunityFeed (parent). Mutations (publish now /
 * reschedule / delete) call back so the parent stays the single source
 * of truth for the count that also feeds the caretaker overview.
 */

export interface ScheduledPost {
  id: string
  post_type: string
  title: string | null
  body: string
  is_pinned: boolean
  scheduled_for: string | null
  scheduling_timezone: string | null
  author_name: string
}

interface Props {
  spaceSlug: string
  items: ScheduledPost[] | null
  /** 'today' hides everything scheduled outside the current calendar day. */
  dateFilter: 'all' | 'today'
  onClearDateFilter: () => void
  onItemsChanged: (next: ScheduledPost[]) => void
  /** Focus / expand the composer. Used by the empty state. */
  onStartConversation: () => void
}

export default function ScheduledPostsList({
  spaceSlug, items, dateFilter, onClearDateFilter, onItemsChanged, onStartConversation,
}: Props) {
  const reload = useCallback(async () => {
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/community/scheduled`),
        { credentials: 'include' },
      )
      if (!res.ok) return
      const data = (await res.json()) as ScheduledPost[]
      onItemsChanged(data)
    } catch {
      // Non-fatal; the next render's fresh fetch will resync.
    }
  }, [spaceSlug, onItemsChanged])

  const filtered = useMemo(() => {
    if (!items) return null
    if (dateFilter !== 'today') return items
    const start = new Date(); start.setHours(0, 0, 0, 0)
    const end = new Date(); end.setHours(23, 59, 59, 999)
    return items.filter((p) => {
      if (!p.scheduled_for) return false
      const t = Date.parse(p.scheduled_for)
      return Number.isFinite(t) && t >= start.getTime() && t <= end.getTime()
    })
  }, [items, dateFilter])

  // Loading vs empty vs populated.
  if (items === null) {
    return (
      <QueueShell>
        <p className="rounded-2xl bg-white px-5 py-4 text-[13px] italic text-slate-500"
           style={{ border: '1px solid rgba(0,0,0,0.07)' }}>
          Loading the queue…
        </p>
      </QueueShell>
    )
  }

  if (!filtered || filtered.length === 0) {
    return (
      <QueueShell dateFilter={dateFilter} onClearDateFilter={onClearDateFilter}>
        <div
          className="rounded-2xl bg-white px-8 py-10 text-center"
          style={{ border: '1px dashed rgba(12,24,38,0.14)' }}
        >
          <p className="mb-2 font-serif text-xl text-navy-800">
            {dateFilter === 'today' ? 'Nothing publishing today.' : 'Nothing in the queue'}
          </p>
          <p className="mx-auto mb-5 max-w-md text-[13.5px] leading-relaxed" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
            {dateFilter === 'today'
              ? 'When you schedule a conversation for today it will appear here.'
              : 'Schedule conversations ahead of time to create a steady rhythm for your collective.'}
          </p>
          <button
            type="button"
            onClick={onStartConversation}
            className="rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'var(--fc-accent, #0d9488)' }}
          >
            Start a conversation →
          </button>
        </div>
      </QueueShell>
    )
  }

  const groups = groupByDate(filtered)

  return (
    <QueueShell dateFilter={dateFilter} onClearDateFilter={onClearDateFilter}>
      <div className="flex flex-col gap-6">
        {groups.map((g) => (
          <section key={g.key}>
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
              {g.label}
            </p>
            <div
              className="overflow-hidden rounded-2xl bg-white divide-y"
              style={{ border: '1px solid rgba(0,0,0,0.07)', borderColor: 'rgba(0,0,0,0.06)' }}
            >
              {g.items.map((p) => (
                <QueueRow
                  key={p.id}
                  post={p}
                  spaceSlug={spaceSlug}
                  onChanged={reload}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </QueueShell>
  )
}

function QueueShell({
  children, dateFilter, onClearDateFilter,
}: {
  children: React.ReactNode
  dateFilter?: 'all' | 'today'
  onClearDateFilter?: () => void
}) {
  return (
    <div>
      {dateFilter === 'today' && onClearDateFilter && (
        <div className="mb-3 flex items-center gap-2">
          <span
            className="rounded-full px-3 py-1 text-[12px] font-medium"
            style={{ background: 'var(--fc-accent, #0d9488)', color: '#FFFFFF' }}
          >
            Publishing today
          </span>
          <button
            type="button"
            onClick={onClearDateFilter}
            className="text-[12px] text-slate-500 hover:text-slate-700"
          >
            Show all
          </button>
        </div>
      )}
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function QueueRow({
  post, spaceSlug, onChanged,
}: {
  post: ScheduledPost
  spaceSlug: string
  onChanged: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [rescheduling, setRescheduling] = useState(false)
  const [busy, setBusy] = useState<'publish' | 'delete' | 'reschedule' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const initial = parseScheduled(post.scheduled_for)
  const [date, setDate] = useState(initial.date)
  const [time, setTime] = useState(initial.time)

  const tz = post.scheduling_timezone || getLocalTimezone()
  const timeLabel = post.scheduled_for
    ? new Date(post.scheduled_for).toLocaleTimeString('en-AU', {
        hour: 'numeric', minute: '2-digit', hour12: true,
      }).toLowerCase().replace(/\s+/g, '')
    : '—'
  const previewText = post.body?.replace(/<[^>]+>/g, '').trim() || ''
  const heading = (post.title && post.title.trim())
    || truncate(previewText, 80)
    || 'Untitled conversation'

  async function publishNow() {
    if (!confirm(`Publish "${heading}" now?`)) return
    setBusy('publish'); setErr(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/community/${post.id}/publish-now`),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `HTTP ${res.status}`)
      }
      onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Publish failed.')
    } finally {
      setBusy(null); setMenuOpen(false)
    }
  }

  async function saveReschedule() {
    if (!date || !time) { setErr('Choose a date and time.'); return }
    const iso = new Date(`${date}T${time}`).toISOString()
    if (new Date(iso).getTime() <= Date.now()) {
      setErr('Scheduled time must be in the future.')
      return
    }
    setBusy('reschedule'); setErr(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/community/${post.id}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scheduled_for: iso,
            scheduling_timezone: getLocalTimezone(),
          }),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `HTTP ${res.status}`)
      }
      setRescheduling(false)
      onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Reschedule failed.')
    } finally {
      setBusy(null)
    }
  }

  async function cancelScheduled() {
    // Deletion of the record is currently the safest way to cancel a
    // scheduled conversation — the draft state isn't implemented, so
    // "cancel" here means "will not publish, gone from the queue".
    if (!confirm('Cancel this scheduled conversation? It will not be published. This cannot be undone.')) return
    setBusy('delete'); setErr(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/community/${post.id}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Cancel failed.')
    } finally {
      setBusy(null); setMenuOpen(false)
    }
  }

  return (
    <div className="flex items-start gap-4 px-5 py-4">
      {/* Time column */}
      <div className="w-16 shrink-0 pt-0.5">
        <p className="font-serif text-[15px] leading-tight" style={{ color: '#0C1826' }}>
          {timeLabel}
        </p>
        <p className="mt-0.5 text-[10.5px] uppercase tracking-wide" style={{ color: 'rgba(12,24,38,0.50)' }}>
          {tz}
        </p>
      </div>

      {/* Main */}
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <PostTypeTag type={post.post_type} />
          {post.is_pinned && (
            <span
              className="rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(212,176,72,0.14)', color: '#8A6A15' }}
            >
              Start here
            </span>
          )}
        </div>
        <p className="font-serif text-[16px] leading-snug text-navy-900">{heading}</p>
        {post.title && previewText && (
          <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
            {previewText}
          </p>
        )}
        <p className="mt-1.5 text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
          Scheduled by {post.author_name}
        </p>

        {rescheduling && (
          <div
            className="mt-3 flex flex-wrap items-center gap-2 rounded-lg px-3 py-2"
            style={{ background: 'rgba(212,176,72,0.06)', border: '1px solid rgba(212,176,72,0.20)' }}
          >
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] focus:border-[color:var(--fc-accent,#38A09E)] focus:outline-none"
            />
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] focus:border-[color:var(--fc-accent,#38A09E)] focus:outline-none"
            />
            <span
              className="rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.62)' }}
            >
              {getLocalTimezone()}
            </span>
            <button
              type="button"
              onClick={saveReschedule}
              disabled={busy === 'reschedule'}
              className="rounded-full px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
              style={{ background: 'var(--fc-accent, #0d9488)' }}
            >
              {busy === 'reschedule' ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => { setRescheduling(false); setErr(null) }}
              className="text-[12px] text-slate-500 hover:text-slate-700"
            >
              Cancel
            </button>
          </div>
        )}

        {err && <p className="mt-2 text-[12px] text-red-500">{err}</p>}
      </div>

      {/* Actions — restrained overflow menu */}
      <div className="relative shrink-0">
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="Actions"
          className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" />
          </svg>
        </button>
        {menuOpen && (
          <div
            className="absolute right-0 z-20 mt-1 w-52 rounded-xl border border-slate-200 bg-white py-1 shadow-lg"
            onMouseLeave={() => setMenuOpen(false)}
          >
            <button
              type="button"
              onClick={() => { setMenuOpen(false); setRescheduling(true) }}
              className="w-full px-4 py-2.5 text-left text-[13px] text-navy-900 hover:bg-slate-50"
            >
              Reschedule
            </button>
            <button
              type="button"
              onClick={publishNow}
              disabled={busy !== null}
              className="w-full px-4 py-2.5 text-left text-[13px] text-navy-900 hover:bg-slate-50 disabled:opacity-50"
            >
              {busy === 'publish' ? 'Publishing…' : 'Publish now'}
            </button>
            <div className="my-1 h-px bg-slate-100" />
            <button
              type="button"
              onClick={cancelScheduled}
              disabled={busy !== null}
              className="w-full px-4 py-2.5 text-left text-[13px] text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              {busy === 'delete' ? 'Cancelling…' : 'Cancel scheduled'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Date-group helpers
// ---------------------------------------------------------------------------

interface DateGroup {
  key: string
  label: string
  items: ScheduledPost[]
}

function groupByDate(posts: ScheduledPost[]): DateGroup[] {
  const withTime = posts
    .map((p) => ({ p, t: p.scheduled_for ? Date.parse(p.scheduled_for) : NaN }))
    .filter((x) => Number.isFinite(x.t))
    .sort((a, b) => a.t - b.t)

  const groups = new Map<string, DateGroup>()
  for (const { p, t } of withTime) {
    const d = new Date(t)
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
    if (!groups.has(key)) {
      groups.set(key, { key, label: humanDate(d), items: [] })
    }
    groups.get(key)!.items.push(p)
  }
  return Array.from(groups.values())
}

function humanDate(d: Date): string {
  const now = new Date()
  const startOfDay = (dt: Date) => new Date(dt.getFullYear(), dt.getMonth(), dt.getDate()).getTime()
  const days = Math.round((startOfDay(d) - startOfDay(now)) / 86400000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  if (days > 1 && days < 7) {
    return d.toLocaleDateString('en-AU', { weekday: 'long', day: 'numeric', month: 'long' })
  }
  return d.toLocaleDateString('en-AU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

function truncate(s: string, n: number): string {
  s = s.replace(/\s+/g, ' ').trim()
  return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s
}

function parseScheduled(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: '', time: '' }
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return { date: '', time: '' }
  const pad = (n: number) => n.toString().padStart(2, '0')
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  }
}

function getLocalTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Local time'
  } catch {
    return 'Local time'
  }
}
