'use client'

// TODO: creator replies
// TODO: threaded replies
// TODO: mark comment as answered
// TODO: comment notifications
// TODO: moderation tools (hide/delete by creator/admin)
// TODO: per-step comments on/off toggle (creator setting)

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { StepComment } from '@/types/platform'

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function Avatar({ author }: { author: StepComment['author'] }) {
  const initials = (author.name || author.email.split('@')[0])
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
  return (
    <div
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-100 text-[11px] font-semibold text-teal-700"
      aria-hidden="true"
    >
      {initials}
    </div>
  )
}

interface Props {
  spaceSlug: string
  pathwaySlug: string
  stepSlug: string
  initialComments: StepComment[]
}

export default function StepDiscussion({
  spaceSlug,
  pathwaySlug,
  stepSlug,
  initialComments,
}: Props) {
  const [comments, setComments] = useState<StepComment[]>(initialComments)
  const [body, setBody] = useState('')
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const base = `/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${stepSlug}/comments`

  async function handlePost() {
    const trimmed = body.trim()
    if (!trimmed) return
    setPosting(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(base), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body: trimmed }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data?.detail ?? 'Could not post comment. Please try again.')
        return
      }
      const created: StepComment = await res.json()
      setComments((prev) => [...prev, created])
      setBody('')
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setPosting(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      handlePost()
    }
  }

  return (
    <div className="mt-10 pt-8 border-t border-border">
      <div className="mb-1 h-[2px] w-6 rounded-full bg-teal-400" />
      <h2 className="mb-1 font-serif text-lg text-slate-900">Questions &amp; discussion</h2>
      <p className="mb-6 text-sm text-slate-500">
        Visible to others in this pathway. Ask a question, share what landed, or add something others may find helpful.
      </p>

      {/* Composer */}
      <div className="mb-8 overflow-hidden rounded-2xl border border-border bg-white">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          maxLength={2000}
          placeholder="Ask a question or share a thought about this step…"
          className="w-full resize-none px-5 pt-4 pb-3 text-[15px] leading-relaxed text-navy-900 placeholder:text-slate-400 focus:outline-none"
          style={{ fontFamily: 'inherit' }}
        />
        <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
          {error ? (
            <span className="text-xs text-red-500">{error}</span>
          ) : (
            <span className="text-xs text-slate-400">
              {body.trim().length > 0 ? `${body.length}/2000` : 'Cmd+Enter to post'}
            </span>
          )}
          <button
            onClick={handlePost}
            disabled={!body.trim() || posting}
            className={[
              'rounded-full px-4 py-1.5 text-xs font-semibold text-white transition-colors',
              body.trim() && !posting
                ? 'bg-teal-600 hover:bg-teal-700 cursor-pointer'
                : 'bg-slate-200 text-slate-400 cursor-not-allowed',
            ].join(' ')}
          >
            {posting ? 'Posting…' : 'Post'}
          </button>
        </div>
      </div>

      {/* Comment list */}
      {comments.length === 0 ? (
        <p className="text-sm text-slate-500">
          No discussion yet. Be the first to ask a question or share a thought.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {comments.map((comment) => (
            <div key={comment.id} className="flex gap-3">
              <Avatar author={comment.author} />
              <div className="min-w-0 flex-1 rounded-2xl border border-border bg-white px-4 py-3">
                <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                  <span className="text-[13px] font-semibold text-navy-900">
                    {comment.author.display_name}
                  </span>
                  <span className="text-[11px] text-slate-400">
                    {formatDate(comment.created_at)}
                  </span>
                </div>
                <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-slate-600">
                  {comment.body}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
