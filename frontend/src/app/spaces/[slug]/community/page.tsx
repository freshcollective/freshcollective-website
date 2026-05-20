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
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">

      {/* ── Left column: intro + composer + feed ── */}
      <div className="min-w-0">

        {/* Intro card — flat navy matching dashboard Explore card */}
        <div
          className="mb-5 overflow-hidden rounded-2xl px-7 py-7"
          style={{
            background: '#071824',
            border: '1px solid rgba(66,199,198,0.10)',
            boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
          }}
        >
          <div
            className="mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
          />
          <h2 className="mb-2 leading-snug">
            <span
              className="inline-block text-2xl font-semibold"
              style={{
                background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              Collective
            </span>
          </h2>
          <p className="text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.72)' }}>
            A place to reflect, share, ask questions, and move through the work together.
          </p>
        </div>

        {/* Composer — top of page, before the feed */}
        <div className="mb-6">
          <CreatePostForm spaceSlug={slug} />
        </div>

        {/* Pinned posts */}
        {pinned.length > 0 && (
          <section className="mb-5">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              Pinned
            </p>
            <div className="flex flex-col gap-3">
              {pinned.map((p) => (
                <PostCard key={p.id} post={p} spaceSlug={slug} />
              ))}
            </div>
          </section>
        )}

        {/* Feed */}
        {feed.length > 0 ? (
          <section>
            {(pinned.length > 0) && (
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                Recent
              </p>
            )}
            <div className="flex flex-col gap-3">
              {feed.map((p) => (
                <PostCard key={p.id} post={p} spaceSlug={slug} />
              ))}
            </div>
          </section>
        ) : (
          !pinned.length && (
            <div
              className="rounded-2xl bg-white px-7 py-10 text-center"
              style={{ border: '1px solid rgba(0,0,0,0.07)' }}
            >
              <p className="mb-2 font-serif text-xl text-navy-800">
                The conversation begins with you.
              </p>
              <p className="mx-auto max-w-sm text-[13px] leading-relaxed text-slate-400">
                Share what you are noticing, ask what you are sitting with, or respond when something touches you.
              </p>
            </div>
          )
        )}
      </div>

      {/* ── Right column: sidebar panel (desktop only) ── */}
      <aside className="hidden lg:block">
        <div className="sticky top-6">
          {/* TODO: replace this placeholder with creator-managed Collective sidebar content. */}
          <div
            className="rounded-2xl bg-white px-5 py-6"
            style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <div
              className="mb-3 h-[2px] w-5 rounded-full"
              style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
            />
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              Important
            </p>

            <div className="mt-4 flex flex-col gap-4">
              <div>
                <p className="mb-1 text-[12px] font-semibold text-navy-900">Start here</p>
                <p className="text-[12px] leading-relaxed text-slate-400">
                  Creators can add a welcome message or first step here.
                </p>
              </div>
              <div className="h-px bg-slate-100" />
              <div>
                <p className="mb-1 text-[12px] font-semibold text-navy-900">Upcoming focus</p>
                <p className="text-[12px] leading-relaxed text-slate-400">
                  A weekly theme or prompt can live here.
                </p>
              </div>
              <div className="h-px bg-slate-100" />
              <div>
                <p className="mb-1 text-[12px] font-semibold text-navy-900">Helpful links</p>
                <p className="text-[12px] leading-relaxed text-slate-400">
                  Key resources and links will appear here.
                </p>
              </div>
            </div>

            <p className="mt-5 text-[11px] leading-relaxed text-slate-300">
              Creators will be able to manage this panel from Creator Studio.
            </p>
          </div>
        </div>
      </aside>

    </div>
  )
}
