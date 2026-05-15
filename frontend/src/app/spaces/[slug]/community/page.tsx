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
      <div
        className="mb-8 overflow-hidden rounded-2xl px-7 py-8"
        style={{
          background:
            'radial-gradient(rgba(66,199,198,0.07) 1px, transparent 1px), ' +
            'radial-gradient(ellipse at 80% 20%, rgba(66,199,198,0.22), transparent 45%), ' +
            'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0F5E5C 100%)',
          backgroundSize: '22px 22px, auto, auto',
        }}
      >
        <div
          className="mb-3 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
        />
        <h2 className="font-serif text-2xl" style={{ color: '#FFFFFF' }}>Community</h2>
        <p className="mt-2 text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.65)' }}>
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
