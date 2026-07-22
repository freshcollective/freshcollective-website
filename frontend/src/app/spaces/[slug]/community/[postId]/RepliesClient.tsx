'use client'

import { useMemo, useState } from 'react'
import Avatar from '@/components/ui/Avatar'
import CommunityImage from '@/components/community/CommunityImage'
import CreateCommentForm from '@/components/community/CreateCommentForm'
import MentionText from '@/components/community/MentionText'
import ModerationMenu from '@/components/community/ModerationMenu'
import ReactionBar from '@/components/community/ReactionBar'
import { resolveMediaUrl } from '@/lib/api'
import type { CommentItem } from '@/types/platform'

/**
 * RepliesClient — the interactive slice of the post detail page.
 *
 * Owns the "which comment am I replying to" state so the composer at
 * the bottom of the thread can render its "Replying to @name" pill,
 * and so tapping "Reply" on any comment simply sets that state.
 *
 * Reply comments render with a small "In reply to @author" caption
 * above the body — a light way to signal threading without deep
 * visual nesting.
 */

interface ReplyTarget {
  commentId: string
  authorName: string
}

interface Props {
  spaceSlug: string
  postId: string
  comments: CommentItem[]
  canModerate: boolean
  /** Current viewer id — enables the Community Care Report action on
   *  any comment authored by someone other than the viewer. */
  viewerId?: string | null
  /** Map of user_id → display_name for the current space, used to
   *  render @mention chips. */
  memberNamesById: Record<string, string>
}

function formatDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })
}

export default function RepliesClient({
  spaceSlug, postId, comments, canModerate, viewerId, memberNamesById,
}: Props) {
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null)

  // Cache display names for comments we're rendering, so parent lookup
  // works even when the parent author isn't in the space members list.
  const commentAuthorNameById = useMemo(() => {
    const map: Record<string, string> = {}
    for (const c of comments) map[c.author.id] = c.author.display_name
    return map
  }, [comments])

  return (
    <>
      <h2 className="mb-6 font-serif text-xl text-navy-900">
        {comments.length === 0
          ? 'Replies'
          : `${comments.length} ${comments.length === 1 ? 'reply' : 'replies'}`}
      </h2>

      {comments.length > 0 ? (
        <div
          className="mb-2 rounded-2xl bg-white px-5 divide-y divide-border"
          style={{ border: '1px solid var(--fc-accent-line, rgba(56,160,158,0.20))' }}
        >
          {comments.map((c) => {
            const parentName =
              c.parent_author_name
              ?? (c.parent_comment_id ? commentAuthorNameById[c.parent_comment_id] : null)
            return (
              <CommentBlock
                key={c.id}
                comment={c}
                spaceSlug={spaceSlug}
                postId={postId}
                canModerate={canModerate}
                viewerId={viewerId}
                parentAuthorName={parentName ?? null}
                memberNamesById={memberNamesById}
                onReply={() => setReplyTo({ commentId: c.id, authorName: c.author.display_name })}
              />
            )
          })}
        </div>
      ) : (
        <p className="mb-6 text-sm text-black">
          No replies yet. Be the first to respond.
        </p>
      )}

      <CreateCommentForm
        spaceSlug={spaceSlug}
        postId={postId}
        replyTo={replyTo}
        onCancelReply={() => setReplyTo(null)}
      />
    </>
  )
}

function CommentBlock({
  comment, spaceSlug, postId, canModerate, viewerId, parentAuthorName, memberNamesById, onReply,
}: {
  comment: CommentItem
  spaceSlug: string
  postId: string
  canModerate: boolean
  viewerId?: string | null
  parentAuthorName: string | null
  memberNamesById: Record<string, string>
  onReply: () => void
}) {
  const mentionedNames = (comment.mentioned_user_ids ?? [])
    .map((id) => memberNamesById[id])
    .filter((n): n is string => !!n)

  return (
    <div className="flex gap-4 py-5">
      <Avatar name={comment.author.display_name} size="sm" />
      <div className="flex-1 min-w-0">
        {parentAuthorName && (
          <p
            className="mb-1 text-[11px] italic"
            style={{ color: 'rgba(12,24,38,0.55)' }}
          >
            In reply to @{parentAuthorName}
          </p>
        )}
        <div className="mb-1 flex items-center justify-between gap-3">
          <div className="flex items-baseline gap-3">
            <span className="text-sm font-medium text-navy-800">
              {comment.author.display_name}
            </span>
            <span className="text-xs text-black">{formatDate(comment.created_at)}</span>
          </div>
          {(canModerate || (!!viewerId && viewerId !== comment.author.id)) && (
            <ModerationMenu
              spaceSlug={spaceSlug}
              postId={postId}
              commentId={comment.id}
              canRemove={canModerate}
              hideReport={!viewerId || viewerId === comment.author.id}
            />
          )}
        </div>
        {comment.body.split('\n').filter(Boolean).map((para, i) => (
          <p key={i} className="text-sm leading-relaxed text-black">
            <MentionText body={para} mentionedNames={mentionedNames} />
          </p>
        ))}
        {comment.image_url && (
          <CommunityImage
            src={resolveMediaUrl(comment.image_url) ?? ''}
            alt="Attached image"
            className="mt-2 max-h-64 w-full rounded-lg object-cover"
          />
        )}
        <div className="mt-2 flex items-center gap-3">
          <ReactionBar
            spaceSlug={spaceSlug}
            postId={postId}
            commentId={comment.id}
            initialReactions={comment.reactions}
          />
          <button
            type="button"
            onClick={onReply}
            className="text-[12px] transition-colors hover:underline"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            Reply
          </button>
        </div>
      </div>
    </div>
  )
}
