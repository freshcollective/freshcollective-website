'use client'

import { forwardRef, useImperativeHandle, useRef, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { Button } from '@/components/platform'
import { PlusIcon } from '@/components/creator/PrimaryActionLink'
import EmojiPicker from './EmojiPicker'
import MentionTextarea, { type MentionTextareaHandle } from './MentionTextarea'
import PollComposer, { EMPTY_POLL, type PollComposerValue } from './PollComposer'
import { POST_TYPE_OPTIONS } from './PostTypeTag'

/**
 * CreatePostForm — collapsed button → expanded form. Supports every
 * Community Phase 1 addition:
 *
 *   - Extended type vocabulary (Reflection, Question, Poll, Announcement,
 *     Celebration, Share).
 *   - Poll composer inline when type = Poll.
 *   - @mention autocomplete via MentionTextarea.
 *
 * Exposes an imperative handle so callers (e.g. the queue empty state)
 * can programmatically open + focus the composer.
 */

export interface CreatePostFormHandle {
  /** Expand the composer and focus the body input. Scrolls into view. */
  openComposer: () => void
}

interface CreatePostFormProps {
  spaceSlug: string
  /** When set, the new post is routed to this Channel. Omitting sends
   *  to the space's Common Room (server default). */
  channelSlug?: string
  /** Creator-only: expose the "Add to Start here" toggle on the composer. */
  canPin?: boolean
  /** Creator-only: expose the "Schedule for later" publishing mode.
   *  When false, only immediate publish is available. */
  canSchedule?: boolean
  /** Draft collectives cannot receive scheduled posts. Passing true
   *  disables the "Schedule for later" option with a helpful message. */
  isDraftCollective?: boolean
}

const CreatePostForm = forwardRef<CreatePostFormHandle, CreatePostFormProps>(function CreatePostForm({
  spaceSlug,
  channelSlug,
  canPin = false,
  canSchedule = false,
  isDraftCollective = false,
}: CreatePostFormProps, ref) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [postType, setPostType] = useState('reflection')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [mentionedIds, setMentionedIds] = useState<string[]>([])
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [poll, setPoll] = useState<PollComposerValue>(EMPTY_POLL)
  const [pinOnCreate, setPinOnCreate] = useState(false)
  // Community Phase 2 — scheduling state
  const [publishMode, setPublishMode] = useState<'now' | 'later'>('now')
  const [scheduleDate, setScheduleDate] = useState('') // yyyy-mm-dd
  const [scheduleTime, setScheduleTime] = useState('') // HH:MM (24h, browser local)
  const displayTz = getLocalTimezone()
  const [error, setError] = useState('')
  const [isPending, startTransition] = useTransition()
  const mentionRef = useRef<MentionTextareaHandle>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const rootRef = useRef<HTMLElement>(null)

  useImperativeHandle(ref, () => ({
    openComposer: () => {
      setOpen(true)
      // Give the form a tick to mount before focusing/scrolling.
      setTimeout(() => {
        rootRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        mentionRef.current?.focus()
      }, 60)
    },
  }))

  function reset() {
    setOpen(false)
    setTitle('')
    setBody('')
    setMentionedIds([])
    setPostType('reflection')
    setPoll(EMPTY_POLL)
    setPinOnCreate(false)
    setPublishMode('now')
    setScheduleDate('')
    setScheduleTime('')
    setError('')
    setImageUrl(null)
    setImagePreview(null)
    mentionRef.current?.clear()
  }

  function scheduledForIso(): string | null {
    if (publishMode !== 'later' || !scheduleDate || !scheduleTime) return null
    // Parse as a *local* time and let the browser convert to UTC ISO.
    const local = new Date(`${scheduleDate}T${scheduleTime}`)
    if (Number.isNaN(local.getTime())) return null
    return local.toISOString()
  }

  function scheduleSummary(): string {
    const iso = scheduledForIso()
    if (!iso) return ''
    const d = new Date(iso)
    return d.toLocaleString('en-AU', {
      weekday: 'long', day: 'numeric', month: 'long',
      hour: 'numeric', minute: '2-digit', hour12: true,
    }) + ` ${displayTz}`
  }

  function insertEmoji(emoji: string) {
    // Emoji picker still works at the end for simplicity.
    setBody((b) => b + emoji)
  }

  async function handleImageChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setImagePreview(URL.createObjectURL(file))
    setUploading(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/community/upload-image`), {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail || 'Image upload failed.')
        setImagePreview(null)
        return
      }
      const { url } = await res.json()
      setImageUrl(url)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (postType !== 'poll' && !body.trim()) {
      setError('Please write something before sharing.')
      return
    }
    if (postType === 'poll') {
      const labels = poll.options.map((o) => o.label.trim()).filter(Boolean)
      if (labels.length < 2) {
        setError('A poll needs at least two options.')
        return
      }
    }

    // Scheduling — validate before we spend a network round-trip.
    const scheduledForValue = scheduledForIso()
    if (publishMode === 'later') {
      if (!scheduledForValue) {
        setError('Please choose a publication date and time.')
        return
      }
      if (new Date(scheduledForValue).getTime() <= Date.now()) {
        setError('Scheduled time must be in the future.')
        return
      }
      if (postType === 'poll' && poll.closes_at) {
        if (new Date(poll.closes_at).getTime() <= new Date(scheduledForValue).getTime()) {
          setError('Poll close date must be after the scheduled publication time.')
          return
        }
      }
    }

    const payload: Record<string, unknown> = {
      post_type: postType,
      title: title.trim() || null,
      body: body.trim(),
      image_url: imageUrl || null,
      mentioned_user_ids: mentionedIds,
      is_pinned: canPin ? pinOnCreate : false,
    }
    if (channelSlug) payload.channel_slug = channelSlug
    if (postType === 'poll') {
      payload.poll = {
        options: poll.options.map((o) => ({ label: o.label.trim() })).filter((o) => o.label),
        allow_multiple: poll.allow_multiple,
        is_anonymous: poll.is_anonymous,
        show_results_before_vote: poll.show_results_before_vote,
        closes_at: poll.closes_at,
      }
    }
    if (scheduledForValue) {
      payload.scheduled_for = scheduledForValue
      payload.scheduling_timezone = displayTz
    }

    const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/community`), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      setError(typeof data.detail === 'string' ? data.detail : 'Something went wrong. Please try again.')
      return
    }

    reset()
    startTransition(() => router.refresh())
  }

  if (!open) {
    return (
      <div ref={rootRef as React.RefObject<HTMLDivElement>} className="mb-4">
        <Button
          variant="primary"
          size="md"
          iconStart={<PlusIcon />}
          onClick={() => setOpen(true)}
        >
          Start a conversation
        </Button>
      </div>
    )
  }

  return (
    <form
      ref={rootRef as React.RefObject<HTMLFormElement>}
      onSubmit={handleSubmit}
      className="rounded-xl border border-teal-200 bg-surface px-6 py-5"
    >
      <div className="mb-4 flex items-center justify-between">
        <select
          value={postType}
          onChange={(e) => setPostType(e.target.value)}
          className="rounded-full border border-border bg-background px-3 py-1 text-xs text-black focus:border-teal-400 focus:outline-none"
        >
          {POST_TYPE_OPTIONS.map((t) => (
            <option key={t.value} value={t.value}>{t.icon}  {t.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={reset}
          className="text-xs text-black hover:text-slate-600"
        >
          Cancel
        </button>
      </div>

      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={postType === 'poll' ? 'Ask a question…' : 'Title (optional)'}
        className="mb-3 w-full rounded-lg border border-border bg-surface px-4 py-2 text-sm text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
      />

      <MentionTextarea
        ref={mentionRef}
        spaceSlug={spaceSlug}
        value={body}
        onChange={setBody}
        mentionedIds={mentionedIds}
        onMentionedIdsChange={setMentionedIds}
        rows={4}
        placeholder={postType === 'poll' ? 'Add optional context (or leave blank)…' : 'Write something…'}
      />

      {postType === 'poll' && (
        <PollComposer value={poll} onChange={setPoll} />
      )}

      {/* Image preview */}
      {imagePreview && (
        <div className="relative mt-2 inline-block">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imagePreview} alt="Upload preview" className="max-h-48 rounded-lg object-cover" />
          {uploading && (
            <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-white/60">
              <span className="text-xs text-black">Uploading…</span>
            </div>
          )}
          {!uploading && (
            <button
              type="button"
              onClick={() => { setImageUrl(null); setImagePreview(null) }}
              className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-slate-700 text-[10px] text-white hover:bg-red-500"
            >
              ✕
            </button>
          )}
        </div>
      )}

      {canPin && (
        <label className="mt-3 flex cursor-pointer items-center gap-2 text-[12.5px] text-navy-900">
          <input
            type="checkbox"
            checked={pinOnCreate}
            onChange={(e) => setPinOnCreate(e.target.checked)}
            className="h-4 w-4 accent-teal-500"
          />
          Add to Start here
        </label>
      )}

      {canSchedule && (
        <div
          className="mt-4 rounded-lg px-4 py-3"
          style={{ background: 'rgba(212,176,72,0.06)', border: '1px solid rgba(212,176,72,0.20)' }}
        >
          <div className="flex flex-wrap gap-4 text-[12.5px] text-navy-900">
            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="radio"
                name="publish-mode"
                checked={publishMode === 'now'}
                onChange={() => setPublishMode('now')}
                className="h-4 w-4 accent-teal-500"
              />
              Publish now
            </label>
            <label
              className={`flex items-center gap-2 ${isDraftCollective ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
              title={isDraftCollective ? 'This collective must be published before conversations can be scheduled.' : undefined}
            >
              <input
                type="radio"
                name="publish-mode"
                checked={publishMode === 'later'}
                onChange={() => setPublishMode('later')}
                disabled={isDraftCollective}
                className="h-4 w-4 accent-teal-500"
              />
              Schedule for later
            </label>
          </div>

          {isDraftCollective && (
            <p className="mt-2 text-[12px] italic" style={{ color: '#8A6A15' }}>
              This collective must be published before conversations can be scheduled.
            </p>
          )}

          {publishMode === 'later' && !isDraftCollective && (
            <div className="mt-3 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                  Date
                </label>
                <input
                  type="date"
                  value={scheduleDate}
                  onChange={(e) => setScheduleDate(e.target.value)}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
                />
                <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                  Time
                </label>
                <input
                  type="time"
                  value={scheduleTime}
                  onChange={(e) => setScheduleTime(e.target.value)}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
                />
                <span
                  className="rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
                  style={{ background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.62)' }}
                >
                  {displayTz}
                </span>
              </div>
              {scheduledForIso() && (
                <p className="text-[12.5px] italic" style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}>
                  Scheduled for {scheduleSummary()}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}

      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {/* Image upload */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={handleImageChange}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || !!imagePreview}
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-black transition-colors hover:border-teal-300 hover:text-teal-600 disabled:opacity-40"
            title="Attach image"
          >
            <span>🖼</span>
            <span>Photo</span>
          </button>

          {/* Emoji picker */}
          <EmojiPicker onSelect={insertEmoji} />
        </div>

        <button
          type="submit"
          disabled={isPending || uploading || (postType !== 'poll' && !body.trim())}
          className="rounded-full px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: 'var(--fc-accent, #14b8a6)' }}
        >
          {isPending
            ? (publishMode === 'later' ? 'Scheduling…' : 'Sharing…')
            : (publishMode === 'later' ? 'Schedule' : 'Share')}
        </button>
      </div>
    </form>
  )
})

export default CreatePostForm

// Small helper — the composer displays the browser's IANA timezone name
// next to the date/time inputs so the creator knows exactly when the post
// will appear. Falling back to "UTC" here would be misleading; if the
// browser doesn't advertise a zone we say "Local time" explicitly.
function getLocalTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Local time'
  } catch {
    return 'Local time'
  }
}
