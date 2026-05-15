import Link from 'next/link'
import {
  getContinue,
  getSpacePathwaysProgress,
  getSpaceEvents,
  getCommunityFeed,
} from '@/lib/serverApi'
import ContinueCard from '@/components/spaces/ContinueCard'
import PathwayProgressCard from '@/components/spaces/PathwayProgressCard'
import EventCard from '@/components/spaces/EventCard'
import type { PathwayProgress, EventSummary, ContinueResponse, PostSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-4 text-[10px] font-semibold uppercase tracking-[0.12em] text-teal-600">
      {children}
    </p>
  )
}

function Divider() {
  return <div className="my-10 h-px bg-border" />
}

export default async function SpacePage({ params }: Props) {
  const { slug } = await params

  const [pathwaysProgress, events, continueData, communityFeed]: [
    PathwayProgress[],
    EventSummary[],
    ContinueResponse | null,
    PostSummary[],
  ] = await Promise.all([
    getSpacePathwaysProgress(slug),
    getSpaceEvents(slug),
    getContinue(),
    getCommunityFeed(slug),
  ])

  const activePathways = pathwaysProgress.filter(
    (p) => p.status === 'active' || p.status === 'coming_soon',
  )

  const continuedPathway = continueData
    ? pathwaysProgress.find((p) => p.slug === continueData.pathway_slug)
    : null

  const progressPct =
    continuedPathway && continuedPathway.step_count > 0
      ? Math.round((continuedPathway.completed_count / continuedPathway.step_count) * 100)
      : 0

  // Pick up to 2 recent community posts for the snapshot
  const recentPosts = communityFeed.slice(0, 2)

  return (
    <div className="pb-16">

      {/* ── Continue Your Journey ─────────────────────────────────── */}
      <section className="mb-10">
        <SectionLabel>Your journey</SectionLabel>
        <ContinueCard
          data={continueData}
          progressPct={progressPct}
          stepCount={continuedPathway?.step_count ?? 0}
          completedCount={continuedPathway?.completed_count ?? 0}
        />
      </section>

      {/* ── Pathways ─────────────────────────────────────────────── */}
      {activePathways.length > 0 && (
        <>
          <Divider />
          <section className="mb-10">
            <div className="mb-4 flex items-baseline justify-between">
              <SectionLabel>Pathways</SectionLabel>
              <Link
                href={`/spaces/${slug}/pathways`}
                className="text-xs text-teal-600 hover:underline"
              >
                Browse all →
              </Link>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {activePathways.map((p) => (
                <PathwayProgressCard key={p.id} pathway={p} spaceSlug={slug} />
              ))}
            </div>
          </section>
        </>
      )}

      {/* ── Events + Community ───────────────────────────────────── */}
      <Divider />
      <div className="grid gap-10 lg:grid-cols-2">

        {/* Upcoming Events */}
        <section>
          <SectionLabel>Live experiences</SectionLabel>
          {events.length > 0 ? (
            <div className="flex flex-col gap-3">
              {events.slice(0, 3).map((e) => (
                <EventCard key={e.id} event={e} spaceSlug={slug} />
              ))}
              {events.length > 3 && (
                <Link
                  href={`/spaces/${slug}/events`}
                  className="mt-1 text-xs text-slate-400 hover:text-teal-600"
                >
                  View all events →
                </Link>
              )}
            </div>
          ) : (
            <div
              className="rounded-2xl border bg-white px-6 py-6"
              style={{ borderColor: 'rgba(56,160,158,0.15)', borderLeft: '3px solid rgba(56,160,158,0.30)' }}
            >
              <p className="mb-1 font-serif text-base text-navy-700">
                Nothing scheduled yet.
              </p>
              <p className="text-sm text-slate-400">
                Live calls and gatherings will appear here. Come back soon.
              </p>
            </div>
          )}
        </section>

        {/* Community Snapshot — real data */}
        <section>
          <div className="mb-4 flex items-baseline justify-between">
            <SectionLabel>In the community</SectionLabel>
            <Link
              href={`/spaces/${slug}/community`}
              className="text-xs text-teal-600 hover:underline"
            >
              Open community →
            </Link>
          </div>

          {recentPosts.length > 0 ? (
            <div className="flex flex-col gap-3">
              {recentPosts.map((post) => (
                <Link
                  key={post.id}
                  href={`/spaces/${slug}/community/${post.id}`}
                  className="group block rounded-2xl border border-border bg-white px-5 py-4 transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md"
                >
                  {post.title ? (
                    <p className="mb-1 font-serif text-sm text-navy-800 group-hover:text-teal-700 transition-colors leading-snug">
                      {post.title}
                    </p>
                  ) : (
                    <p className="mb-1 text-sm text-navy-800 group-hover:text-teal-700 transition-colors leading-relaxed line-clamp-2">
                      {post.body.split('\n\n')[0]}
                    </p>
                  )}
                  <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
                    <span>{post.author.display_name}</span>
                    <span>·</span>
                    <span>
                      {post.comment_count === 0
                        ? 'No replies yet'
                        : `${post.comment_count} ${post.comment_count === 1 ? 'reply' : 'replies'}`}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="rounded-2xl border border-border bg-white px-5 py-6">
              <p className="mb-1 font-serif text-base text-navy-700">
                The conversation begins with you.
              </p>
              <p className="mt-1 text-sm text-slate-400">
                Share a reflection, ask a question, or start a discussion.
              </p>
              <Link
                href={`/spaces/${slug}/community`}
                className="mt-3 inline-block text-xs font-medium text-teal-600 hover:underline"
              >
                Open community →
              </Link>
            </div>
          )}
        </section>
      </div>

      {/* ── Welcome note ─────────────────────────────────────────── */}
      <Divider />
      <section>
        <div
          className="rounded-2xl border border-teal-100 px-6 py-5"
          style={{ background: 'rgba(56,160,158,0.04)' }}
        >
          <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-teal-600">
            A note
          </p>
          <p className="font-serif text-lg text-navy-900">
            You are in the right place.
          </p>
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-slate-500">
            This space is designed to grow with you. Start with the REAL Journey,
            return often, and let the structure hold you. Nothing here is about
            speed or perfection.
          </p>
        </div>
      </section>

    </div>
  )
}
