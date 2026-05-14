import Link from 'next/link'
import { getCreatorSpaces, getCreatorPosts } from '@/lib/serverApi'
import type { CreatorPost } from '@/types/platform'

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

const POST_TYPE_LABEL: Record<string, string> = {
  prompt: 'Prompt',
  reflection: 'Reflection',
  discussion: 'Discussion',
  announcement: 'Announcement',
}

export default async function CommunityPage() {
  const spaces = await getCreatorSpaces()
  const primarySpace = spaces[0] ?? null
  const posts: CreatorPost[] = primarySpace ? await getCreatorPosts(primarySpace.slug) : []

  return (
    <div className="max-w-4xl px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <p
            className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Creator Studio
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Community</h1>
        </div>
        {primarySpace && (
          <Link
            href={`/creator/spaces/${primarySpace.slug}/community`}
            className="shrink-0 rounded-lg border border-border bg-white px-4 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            Manage →
          </Link>
        )}
      </div>

      {/* No collective yet */}
      {!primarySpace && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-1.5 font-serif text-base text-navy-900">No collective yet</p>
          <p className="mb-5 text-sm text-slate-400">
            Set up your collective first, then you can post prompts and start conversations.
          </p>
          <Link
            href="/creator-studio/create"
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create collective
          </Link>
        </div>
      )}

      {/* Collective exists but no posts */}
      {primarySpace && posts.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-1.5 font-serif text-base text-navy-900">No community posts yet.</p>
          <p className="mb-5 text-sm text-slate-400">
            Start with a simple prompt to invite reflection, conversation, or shared practice.
          </p>
          <Link
            href={`/creator/spaces/${primarySpace.slug}/community`}
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Add community prompt
          </Link>
        </div>
      )}

      {/* Posts feed */}
      {posts.length > 0 && (
        <div className="space-y-3">
          {posts.map((post) => (
            <div key={post.id} className="rounded-xl border border-border bg-white p-5">
              <div className="mb-2.5 flex items-start justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                    style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
                  >
                    {POST_TYPE_LABEL[post.post_type] ?? post.post_type}
                  </span>
                  {post.is_pinned && (
                    <span className="text-[11px] text-slate-400">Pinned</span>
                  )}
                </div>
                <span className="shrink-0 text-[11.5px] text-slate-400">
                  {formatDate(post.created_at)}
                </span>
              </div>
              {post.title && (
                <p className="mb-1 font-medium text-navy-900">{post.title}</p>
              )}
              <p className="line-clamp-2 text-[13.5px] leading-relaxed text-slate-500">
                {post.body}
              </p>
              <p className="mt-2 text-[11.5px] text-slate-400">by {post.author_name}</p>
            </div>
          ))}
        </div>
      )}

    </div>
  )
}
