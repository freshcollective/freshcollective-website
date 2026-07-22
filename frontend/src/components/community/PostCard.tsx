'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import PostTypeTag from './PostTypeTag'
import ModerationMenu from './ModerationMenu'
import MentionText from './MentionText'
import PollView from './PollView'
import Avatar from '@/components/ui/Avatar'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type { PostSummary } from '@/types/platform'

function formatPostDate(isoString: string): string {
  const d = new Date(isoString)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays} days ago`
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

interface PostCardProps {
  post: PostSummary
  spaceSlug: string
  canModerate?: boolean
  /** Creator context — surfaces Pin/Unpin action in the overflow menu. */
  canPin?: boolean
  /** Creator context — surfaces Edit action in the overflow menu. */
  canEdit?: boolean
  /** Current viewer id — enables the Community Care Report action for
   *  anyone who is not the post's author. */
  viewerId?: string | null
  /** Map of user_id → display_name so @mention chips render inside the body. */
  memberNamesById?: Record<string, string>
}

export default function PostCard({
  post, spaceSlug, canModerate = false,
  canPin = false, canEdit = false,
  viewerId,
  memberNamesById,
}: PostCardProps) {
  const router = useRouter()
  const [removed, setRemoved] = useState(false)
  const [pinned, setPinned] = useState(post.is_pinned)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState(post.title ?? '')
  const [editBody, setEditBody] = useState(post.body)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const href = `/spaces/${spaceSlug}/community/${post.id}`
  const preview = post.body.replace(/<[^>]+>/g, '').split('\n\n')[0]

  const mentionedNames = (post.mentioned_user_ids ?? [])
    .map((id) => memberNamesById?.[id])
    .filter((n): n is string => !!n)

  if (removed) return null

  const hasPoll = post.poll != null
  const interactive = hasPoll || editing

  async function saveEdit() {
    setSaving(true)
    setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/community/${post.id}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: editTitle.trim() || null,
            body: editBody.trim(),
          }),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Save failed (${res.status})`)
      }
      setEditing(false)
      router.refresh()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative group rounded-2xl border border-border bg-white px-6 py-5 transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md">
      {/* Stretched link — disabled when there's an interactive surface
          (poll or inline edit) so clicks reach the intended target. */}
      {!interactive && (
        <Link href={href} className="absolute inset-0 rounded-2xl" aria-label={post.title ?? 'View post'} />
      )}

      <div className="relative z-10">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <PostTypeTag type={post.post_type} />
            {pinned && (
              <span
                className="rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
                style={{ background: 'rgba(212,176,72,0.14)', color: '#8A6A15' }}
              >
                Start here
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-xs text-black">{formatPostDate(post.created_at)}</span>
            {(canModerate || canPin || canEdit || (!!viewerId && viewerId !== post.author.id)) && (
              <ModerationMenu
                spaceSlug={spaceSlug}
                postId={post.id}
                canPin={canPin}
                isPinned={pinned}
                onPinChanged={setPinned}
                onEdit={canEdit ? () => setEditing(true) : undefined}
                onRemoved={() => setRemoved(true)}
                canRemove={canModerate}
                hideReport={!viewerId || viewerId === post.author.id}
              />
            )}
          </div>
        </div>

        {editing ? (
          <div className="mt-1 flex flex-col gap-3">
            <input
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              placeholder="Title (optional)"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
            />
            <textarea
              value={editBody}
              onChange={(e) => setEditBody(e.target.value)}
              rows={5}
              className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] leading-relaxed text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
            />
            {saveError && <p className="text-[12px] text-red-500">{saveError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setEditing(false)
                  setEditTitle(post.title ?? '')
                  setEditBody(post.body)
                  setSaveError(null)
                }}
                className="rounded-full border border-slate-200 px-4 py-1.5 text-[13px] text-black hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={saveEdit}
                disabled={saving || !editBody.trim()}
                className="rounded-full px-4 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ background: 'var(--fc-accent, #14b8a6)' }}
              >
                {saving ? 'Saving…' : 'Save changes'}
              </button>
            </div>
          </div>
        ) : (
          <>
            {post.title && (
              <h3 className="mb-2 font-serif text-lg leading-snug text-navy-900 group-hover:text-teal-700 transition-colors">
                {hasPoll ? post.title : (
                  <Link href={href} className="hover:underline">{post.title}</Link>
                )}
              </h3>
            )}

            {(preview || post.image_url) && (
              <div className="mb-4 flex gap-4">
                <p className="flex-1 line-clamp-3 text-sm leading-relaxed text-black">
                  <MentionText body={preview} mentionedNames={mentionedNames} />
                </p>
                {post.image_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={resolveMediaUrl(post.image_url) ?? ''}
                    alt=""
                    className="h-16 w-16 shrink-0 rounded-lg object-cover"
                  />
                )}
              </div>
            )}

            {hasPoll && (
              <PollView spaceSlug={spaceSlug} postId={post.id} poll={post.poll!} />
            )}
          </>
        )}

        <div className="mt-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Avatar name={post.author.display_name} size="sm" />
            <span className="text-xs text-black">{post.author.display_name}</span>
          </div>
          <Link
            href={href}
            className="text-xs transition-colors hover:underline"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            {post.comment_count === 0
              ? 'Be the first to reply →'
              : `${post.comment_count} ${post.comment_count === 1 ? 'reply' : 'replies'} →`}
          </Link>
        </div>
      </div>
    </div>
  )
}
