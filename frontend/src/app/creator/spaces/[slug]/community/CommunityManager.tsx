'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { CreatorPost } from '@/types/platform'

const POST_TYPES = [
  { value: 'announcement', label: 'Announcement' },
  { value: 'prompt', label: 'Prompt' },
  { value: 'discussion', label: 'Discussion' },
]

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

const TYPE_LABELS: Record<string, string> = {
  announcement: 'Announcement',
  prompt: 'Prompt',
  discussion: 'Discussion',
  reflection: 'Reflection',
}

async function apiFetch(url: string, options?: RequestInit) {
  const res = await fetch(apiUrl(url), { credentials: 'include', ...options })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {}
    if (process.env.NODE_ENV === 'development') console.error(`${options?.method ?? 'GET'} ${url} → ${detail}`)
    throw new Error(detail)
  }
  return res
}

export default function CommunityManager({
  posts: initialPosts,
  spaceSlug,
}: {
  posts: CreatorPost[]
  spaceSlug: string
}) {
  const [posts, setPosts] = useState(initialPosts)
  const [postType, setPostType] = useState('announcement')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [isPinned, setIsPinned] = useState(false)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const base = `/api/creator/spaces/${spaceSlug}/community`

  async function handlePost(e: React.FormEvent) {
    e.preventDefault()
    if (!body.trim()) return
    setPosting(true)
    setError(null)
    try {
      const res = await apiFetch(base, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          post_type: postType,
          title: title.trim() || null,
          body: body.trim(),
          is_pinned: isPinned,
        }),
      })
      const data: CreatorPost = await res.json()
      setPosts((prev) => [data, ...prev])
      setTitle('')
      setBody('')
      setIsPinned(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not post. Try again.')
    } finally {
      setPosting(false)
    }
  }

  async function togglePin(post: CreatorPost) {
    try {
      await apiFetch(`${base}/${post.id}/pin`, { method: 'PATCH' })
      setPosts((prev) =>
        prev.map((p) => (p.id === post.id ? { ...p, is_pinned: !p.is_pinned } : p)),
      )
    } catch (err) {
      console.error('Pin failed:', err)
    }
  }

  async function hidePost(post: CreatorPost) {
    if (!confirm('Hide this post? Members will no longer see it.')) return
    try {
      await apiFetch(`${base}/${post.id}`, { method: 'DELETE' })
      setPosts((prev) => prev.filter((p) => p.id !== post.id))
    } catch (err) {
      console.error('Hide failed:', err)
    }
  }

  return (
    <div className="flex flex-col gap-10">
      {/* Compose */}
      <form onSubmit={handlePost} className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">New post</p>

        <div className="flex flex-wrap gap-2">
          {POST_TYPES.map((pt) => (
            <button
              key={pt.value}
              type="button"
              onClick={() => setPostType(pt.value)}
              className={[
                'rounded-full border px-3.5 py-1 text-sm transition-colors',
                postType === pt.value
                  ? 'border-navy-900 bg-navy-900 text-white'
                  : 'border-border text-slate-500 hover:border-slate-400',
              ].join(' ')}
            >
              {pt.label}
            </button>
          ))}
        </div>

        {postType !== 'discussion' && (
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title (optional)"
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        )}

        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          required
          rows={5}
          placeholder={
            postType === 'prompt'
              ? 'What question or invitation do you want to offer the community?'
              : postType === 'announcement'
              ? 'Share an update, reminder, or moment with your community…'
              : 'Start the conversation…'
          }
          className="w-full resize-none rounded-xl border border-border bg-white px-5 py-4 text-sm leading-relaxed text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-200"
        />

        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-slate-500">
            <input
              type="checkbox"
              checked={isPinned}
              onChange={(e) => setIsPinned(e.target.checked)}
              className="rounded border-border"
            />
            Pin to top
          </label>
          <div className="flex items-center gap-3">
            {error && <span className="text-xs text-red-500">{error}</span>}
            <button
              type="submit"
              disabled={posting || !body.trim()}
              className="rounded-lg bg-navy-900 px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {posting ? 'Posting…' : 'Post'}
            </button>
          </div>
        </div>
      </form>

      {/* Post list */}
      {posts.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface px-8 py-10 text-center">
          <p className="font-serif text-lg text-navy-700">Nothing posted yet</p>
          <p className="mt-1 text-sm text-slate-400">Start with an announcement or a reflection prompt.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {posts.map((post) => (
            <div key={post.id} className="rounded-xl border border-border bg-surface px-5 py-4">
              <div className="mb-1 flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-0.5 flex flex-wrap items-center gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">
                      {TYPE_LABELS[post.post_type] ?? post.post_type}
                    </span>
                    {post.is_pinned && (
                      <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-teal-600">Pinned</span>
                    )}
                    {!post.is_visible && (
                      <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-red-400">Hidden</span>
                    )}
                  </div>
                  {post.title && <p className="font-medium text-navy-900">{post.title}</p>}
                  <p className="mt-0.5 line-clamp-2 text-sm text-slate-600">{post.body}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    {post.author_name} · {formatDate(post.created_at)}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col gap-1.5 text-right">
                  <button
                    onClick={() => togglePin(post)}
                    className="text-xs text-slate-400 hover:text-navy-700"
                  >
                    {post.is_pinned ? 'Unpin' : 'Pin'}
                  </button>
                  <button
                    onClick={() => hidePost(post)}
                    className="text-xs text-slate-400 hover:text-red-500"
                  >
                    Hide
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
