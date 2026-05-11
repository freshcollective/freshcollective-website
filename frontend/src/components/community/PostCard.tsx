import Link from 'next/link'
import PostTypeTag from './PostTypeTag'
import type { PostSummary } from '@/types/platform'

function formatPostDate(isoString: string): string {
  const d = new Date(isoString)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays} days ago`
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function Initials({ name }: { name: string }) {
  const letters = name
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-navy-100 text-xs font-semibold text-navy-600">
      {letters || '?'}
    </div>
  )
}

interface PostCardProps {
  post: PostSummary
  spaceSlug: string
}

export default function PostCard({ post, spaceSlug }: PostCardProps) {
  const href = `/spaces/${spaceSlug}/community/${post.id}`
  const preview = post.body.split('\n\n')[0]

  return (
    <Link
      href={href}
      className="group block rounded-xl border border-border bg-surface px-6 py-5 transition-shadow hover:shadow-[var(--fc-shadow-card)]"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <PostTypeTag type={post.post_type} />
          {post.is_pinned && (
            <span className="text-xs text-slate-400">Pinned</span>
          )}
        </div>
        <span className="text-xs text-slate-400 shrink-0">{formatPostDate(post.created_at)}</span>
      </div>

      {post.title && (
        <h3 className="mb-2 font-serif text-lg leading-snug text-navy-900 group-hover:text-teal-700 transition-colors">
          {post.title}
        </h3>
      )}

      <p className="mb-4 line-clamp-3 text-sm leading-relaxed text-slate-500">
        {preview}
      </p>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Initials name={post.author.display_name} />
          <span className="text-xs text-slate-500">{post.author.display_name}</span>
        </div>
        <span className="text-xs text-slate-400">
          {post.comment_count === 0
            ? 'Be the first to reply'
            : `${post.comment_count} ${post.comment_count === 1 ? 'reply' : 'replies'}`}
        </span>
      </div>
    </Link>
  )
}
