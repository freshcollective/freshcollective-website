import { getCommunityFeed } from '@/lib/serverApi'
import PostCard from '@/components/community/PostCard'
import CreatePostForm from '@/components/community/CreatePostForm'
import PostTypeTag from '@/components/community/PostTypeTag'
import type { PostSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceCommunityPage({ params }: Props) {
  const { slug } = await params
  const posts: PostSummary[] = await getCommunityFeed(slug)

  const pinned = posts.filter((p) => p.is_pinned)
  const feed = posts.filter((p) => !p.is_pinned)

  return (
    <div className="max-w-2xl">

      {/* Intro */}
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-500" />
        <h2 className="mb-2 font-serif text-2xl text-navy-900">Community</h2>
        <p className="text-sm leading-relaxed text-slate-500">
          A place to reflect, explore, and move through the work together.
          Share what you are noticing. Respond when something resonates.
        </p>
      </div>

      {/* Pinned posts */}
      {pinned.length > 0 && (
        <section className="mb-8">
          <div className="flex flex-col gap-3">
            {pinned.map((p) => (
              <PostCard key={p.id} post={p} spaceSlug={slug} />
            ))}
          </div>
        </section>
      )}

      {/* Divider + create form */}
      {pinned.length > 0 && <div className="mb-8 h-px bg-border" />}

      <section className="mb-6">
        <CreatePostForm spaceSlug={slug} />
      </section>

      {/* Feed */}
      {feed.length > 0 ? (
        <section>
          <div className="flex flex-col gap-3">
            {feed.map((p) => (
              <PostCard key={p.id} post={p} spaceSlug={slug} />
            ))}
          </div>
        </section>
      ) : (
        !pinned.length && (
          <div className="rounded-xl border border-border bg-surface px-7 py-8">
            <p className="mb-1 font-serif text-lg text-navy-700">
              Nothing here yet.
            </p>
            <p className="text-sm leading-relaxed text-slate-400">
              Be the first to share a reflection or start a discussion.
            </p>
          </div>
        )
      )}

    </div>
  )
}
