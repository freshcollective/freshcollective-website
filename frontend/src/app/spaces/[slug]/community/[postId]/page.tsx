import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getCommunityPost } from '@/lib/serverApi'
import PostTypeTag from '@/components/community/PostTypeTag'
import CreateCommentForm from '@/components/community/CreateCommentForm'
import Avatar from '@/components/ui/Avatar'
import type { PostDetail, CommentItem } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; postId: string }>
}

function formatDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })
}

function CommentBlock({ comment }: { comment: CommentItem }) {
  return (
    <div className="flex gap-4 py-5 border-b border-border last:border-0">
      <Avatar name={comment.author.display_name} size="sm" />
      <div className="flex-1 min-w-0">
        <div className="mb-1 flex items-baseline gap-3">
          <span className="text-sm font-medium text-navy-800">
            {comment.author.display_name}
          </span>
          <span className="text-xs text-slate-400">{formatDate(comment.created_at)}</span>
        </div>
        {comment.body.split('\n').filter(Boolean).map((para, i) => (
          <p key={i} className="text-sm leading-relaxed text-slate-600">
            {para}
          </p>
        ))}
      </div>
    </div>
  )
}

export default async function PostDetailPage({ params }: Props) {
  const { slug, postId } = await params
  const post: PostDetail | null = await getCommunityPost(slug, postId)

  if (!post) notFound()

  return (
    <div className="max-w-2xl">

      {/* Back */}
      <Link
        href={`/spaces/${slug}/community`}
        className="mb-7 inline-block text-sm text-slate-400 hover:text-navy-700"
      >
        ← Community
      </Link>

      {/* Post header */}
      <div className="mb-6">
        <div className="mb-3 flex items-center gap-2">
          <PostTypeTag type={post.post_type} />
          {post.is_pinned && (
            <span className="text-xs text-slate-400">Pinned</span>
          )}
        </div>
        {post.title && (
          <h1 className="mb-4 font-serif text-3xl leading-snug text-navy-900">
            {post.title}
          </h1>
        )}
        <div className="flex items-center gap-3">
          <Avatar name={post.author.display_name} size="sm" />
          <div>
            <p className="text-sm font-medium text-navy-800">{post.author.display_name}</p>
            <p className="text-xs text-slate-400">{formatDate(post.created_at)}</p>
          </div>
        </div>
      </div>

      {/* Post body */}
      <div className="mb-10">
        {post.body.split('\n\n').filter(Boolean).map((para, i) => (
          <p key={i} className="mb-3 text-[15px] leading-[1.8] text-slate-600">
            {para}
          </p>
        ))}
      </div>

      {/* Replies */}
      <div className="border-t border-border pt-8">
        <h2 className="mb-6 font-serif text-xl text-navy-900">
          {post.comments.length === 0
            ? 'Replies'
            : `${post.comments.length} ${post.comments.length === 1 ? 'reply' : 'replies'}`}
        </h2>

        {post.comments.length > 0 ? (
          <div className="mb-2 rounded-2xl border border-teal-100 bg-white px-5 divide-y divide-border">
            {post.comments.map((c) => (
              <CommentBlock key={c.id} comment={c} />
            ))}
          </div>
        ) : (
          <p className="mb-6 text-sm text-slate-400">
            No replies yet. Be the first to respond.
          </p>
        )}

        <CreateCommentForm spaceSlug={slug} postId={postId} />
      </div>

    </div>
  )
}
