'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { CreatorPost } from '@/types/platform'

const POST_TYPES = [
  { value: 'announcement', label: 'Announcement' },
  { value: 'prompt', label: 'Prompt' },
  { value: 'discussion', label: 'Discussion' },
]

const TYPE_LABELS: Record<string, string> = {
  announcement: 'Announcement',
  prompt: 'Prompt',
  discussion: 'Discussion',
  reflection: 'Reflection',
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

async function apiFetch(url: string, options?: RequestInit) {
  const res = await fetch(apiUrl(url), { credentials: 'include', ...options })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const b = await res.json()
      detail = typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail)
    } catch {}
    if (process.env.NODE_ENV === 'development') console.error(`${options?.method ?? 'GET'} ${url} → ${detail}`)
    throw new Error(detail)
  }
  return res
}

// ---------------------------------------------------------------------------
// Edit form shown inline
// ---------------------------------------------------------------------------

function EditForm({
  post,
  base,
  onSave,
  onCancel,
}: {
  post: CreatorPost
  base: string
  onSave: (updated: CreatorPost) => void
  onCancel: () => void
}) {
  const [postType, setPostType] = useState(post.post_type)
  const [title, setTitle] = useState(post.title ?? '')
  const [body, setBody] = useState(post.body)
  const [isPinned, setIsPinned] = useState(post.is_pinned)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!body.trim()) return
    setSaving(true)
    setError(null)
    try {
      const res = await apiFetch(`${base}/${post.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          post_type: postType,
          title: title.trim() || null,
          body: body.trim(),
          is_pinned: isPinned,
        }),
      })
      const updated: CreatorPost = await res.json()
      onSave(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSave} className="flex flex-col gap-3 rounded-xl border border-teal-200 bg-teal-50/30 px-5 py-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Editing post</p>

      <div className="flex flex-wrap gap-2">
        {POST_TYPES.map((pt) => (
          <button
            key={pt.value}
            type="button"
            onClick={() => setPostType(pt.value)}
            className={[
              'rounded-full border px-3 py-1 text-xs transition-colors',
              postType === pt.value
                ? 'border-navy-900 bg-navy-900 text-white'
                : 'border-border text-slate-500 hover:border-slate-400',
            ].join(' ')}
          >
            {pt.label}
          </button>
        ))}
      </div>

      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional)"
        className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
      />

      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        required
        rows={4}
        className="w-full resize-none rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-200"
      />

      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-slate-500">
          <input
            type="checkbox"
            checked={isPinned}
            onChange={(e) => setIsPinned(e.target.checked)}
            className="rounded border-border"
          />
          Pinned
        </label>
        <div className="flex items-center gap-3">
          {error && <span className="text-xs text-red-500">{error}</span>}
          <button
            type="button"
            onClick={onCancel}
            className="text-sm text-slate-400 hover:text-slate-600"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving || !body.trim()}
            className="rounded-lg bg-navy-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:opacity-90"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

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
  const [editingId, setEditingId] = useState<string | null>(null)

  const base = `/api/creator/spaces/${spaceSlug}/community`

  // ---------- compose ----------

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
      setError(err instanceof Error ? err.message : 'Could not post.')
    } finally {
      setPosting(false)
    }
  }

  // ---------- edit ----------

  function handleEditSave(updated: CreatorPost) {
    setPosts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
    setEditingId(null)
  }

  // ---------- pin toggle ----------

  async function togglePin(post: CreatorPost) {
    try {
      await apiFetch(`${base}/${post.id}/pin`, { method: 'PATCH' })
      setPosts((prev) => prev.map((p) => (p.id === post.id ? { ...p, is_pinned: !p.is_pinned } : p)))
    } catch (err) {
      console.error('Pin failed:', err)
    }
  }

  // ---------- hide / unhide ----------

  async function toggleVisibility(post: CreatorPost) {
    const action = post.is_visible ? 'hide' : 'unhide'
    try {
      await apiFetch(`${base}/${post.id}/${action}`, { method: 'PATCH' })
      setPosts((prev) => prev.map((p) => (p.id === post.id ? { ...p, is_visible: !p.is_visible } : p)))
    } catch (err) {
      console.error(`${action} failed:`, err)
    }
  }

  // ---------- hard delete ----------

  async function deletePost(post: CreatorPost) {
    if (!confirm(`Delete "${post.title ?? 'this post'}" permanently? This cannot be undone.`)) return
    try {
      await apiFetch(`${base}/${post.id}`, { method: 'DELETE' })
      setPosts((prev) => prev.filter((p) => p.id !== post.id))
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  return (
    <div className="flex flex-col gap-10">

      {/* ── Compose form ── */}
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

      {/* ── Post list ── */}
      {posts.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface px-8 py-10 text-center">
          <p className="font-serif text-lg text-navy-700">Nothing posted yet</p>
          <p className="mt-1 text-sm text-slate-400">Start with an announcement or a reflection prompt.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {posts.map((post) => (
            <div key={post.id} className="rounded-xl border border-border bg-surface">
              {editingId === post.id ? (
                <div className="p-1">
                  <EditForm
                    post={post}
                    base={base}
                    onSave={handleEditSave}
                    onCancel={() => setEditingId(null)}
                  />
                </div>
              ) : (
                <div className="px-5 py-4">
                  {/* Status badges */}
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">
                      {TYPE_LABELS[post.post_type] ?? post.post_type}
                    </span>
                    {post.is_pinned && (
                      <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-teal-600">
                        Pinned
                      </span>
                    )}
                    {!post.is_visible && (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-amber-600">
                        Hidden
                      </span>
                    )}
                  </div>

                  {/* Content */}
                  {post.title && <p className="font-medium text-navy-900">{post.title}</p>}
                  <p className="mt-0.5 line-clamp-3 text-sm text-slate-600">{post.body}</p>
                  <p className="mt-1.5 text-xs text-slate-400">
                    {post.author_name} · {formatDate(post.created_at)}
                  </p>

                  {/* Actions */}
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3">
                    <button
                      onClick={() => setEditingId(post.id)}
                      className="text-xs text-slate-500 hover:text-navy-700"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => togglePin(post)}
                      className="text-xs text-slate-500 hover:text-navy-700"
                    >
                      {post.is_pinned ? 'Unpin' : 'Pin'}
                    </button>
                    <button
                      onClick={() => toggleVisibility(post)}
                      className="text-xs text-slate-500 hover:text-navy-700"
                    >
                      {post.is_visible ? 'Hide' : 'Unhide'}
                    </button>
                    <button
                      onClick={() => deletePost(post)}
                      className="ml-auto text-xs text-slate-400 hover:text-red-500"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
