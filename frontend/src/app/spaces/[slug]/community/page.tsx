import { getCommunityFeed } from '@/lib/serverApi'
import PostCard from '@/components/community/PostCard'
import CreatePostForm from '@/components/community/CreatePostForm'
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
        <div className="mb-2 h-[2px] w-8 rounded-full bg-teal-400" />
        <h2 className="mb-2 font-serif text-2xl text-navy-900">Community</h2>
        <p className="text-sm leading-relaxed text-slate-500">
          A place to reflect, explore, and move through the work together.
          Share what you are noticing. Respond when something resonates.
        </p>
      </div>

      {/* Pinned posts */}
      {pinned.length > 0 && (
        <section className="mb-6">
          <div className="flex flex-col gap-3">
            {pinned.map((p) => (
              <PostCard key={p.id} post={p} spaceSlug={slug} />
            ))}
          </div>
        </section>
      )}

      {/* Feed or empty */}
      {feed.length > 0 ? (
        <>
          <section className="mb-6">
            <div className="flex flex-col gap-3">
              {feed.map((p) => (
                <PostCard key={p.id} post={p} spaceSlug={slug} />
              ))}
            </div>
          </section>
          <div className="h-px bg-border mb-6" />
          <section>
            <CreatePostForm spaceSlug={slug} />
          </section>
        </>
      ) : (
        <>
          {!pinned.length && (
            <div className="mb-6 rounded-2xl border border-teal-100 bg-white px-7 py-10 text-center">
              <p className="mb-2 font-serif text-xl text-navy-800">
                The conversation begins with you.
              </p>
              <p className="mx-auto max-w-sm text-sm leading-relaxed text-slate-400">
                This is a space to share what you&apos;re noticing, ask what you&apos;re sitting with,
                and respond when something touches you.
              </p>
            </div>
          )}
          <section>
            <CreatePostForm spaceSlug={slug} />
          </section>
        </>
      )}

    </div>
  )
}
