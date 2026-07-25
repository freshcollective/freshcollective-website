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
  return d.toLocaleDateString('en-AU', { month: 'short', day: 'numeric', year: 'numeric' })
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
    <div className="mt-14 border-t border-border pt-10">
      <h2 className="font-serif text-[22px] leading-snug text-navy-900">
        Continue the conversation
      </h2>
      <p className="mb-7 mt-2 text-[14.5px] leading-relaxed text-black">
        Share what landed for you, ask a question, or continue the conversation
        with others walking this pathway.
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
            <span className="text-xs text-black">
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
        <div className="rounded-2xl border border-dashed border-slate-200 px-6 py-6 text-[14.5px] leading-relaxed text-black">
          <p>The conversation begins with someone.</p>
          <p className="mt-2">
            If something resonated, ask a question, share a reflection, or simply
            let others know what landed for you.
          </p>
          <p className="mt-2 font-medium" style={{ color: '#0f766e' }}>
            Be the first to begin.
          </p>
        </div>
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
                  <span className="text-[11px] text-black">
                    {formatDate(comment.created_at)}
                  </span>
                </div>
                <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-black">
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
