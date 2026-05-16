import Link from 'next/link'
import { GoldLabel } from '@/components/ui/BrandLabel'
import {
  getContinue,
  getSpacePathwaysProgress,
  getSpaceEvents,
  getCommunityFeed,
} from '@/lib/serverApi'
import ContinueCard from '@/components/spaces/ContinueCard'
import PathwayProgressCard from '@/components/spaces/PathwayProgressCard'
import EventCard, { formatEventDate } from '@/components/spaces/EventCard'
import type { PathwayProgress, EventSummary, ContinueResponse, PostSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
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

  const recentPosts = communityFeed.slice(0, 2)
  const nextEvent = events[0] ?? null
  const nextEventDate = nextEvent ? formatEventDate(nextEvent.starts_at) : null

  return (
    <div className="pb-16">

      {/* ── Your Journey — soft structured pillar-card layout ── */}
      <section className="mb-10">
        <GoldLabel variant="teal" className="mb-4">Your journey</GoldLabel>
        <div className="grid gap-4 lg:grid-cols-3">

          {/* Continue Journey — flex-col wrapper so ContinueCard stretches to row height */}
          <div className="flex flex-col lg:col-span-2">
            <ContinueCard
              data={continueData}
              progressPct={progressPct}
              stepCount={continuedPathway?.step_count ?? 0}
              completedCount={continuedPathway?.completed_count ?? 0}
              className="flex-1"
            />
          </div>

          {/* Right column — Coming Up + Community, equal-height flex children */}
          <div className="flex flex-col gap-4">

            {/* Coming up — pale cream */}
            {nextEvent && nextEventDate ? (
              <Link
                href={`/spaces/${slug}/events/${nextEvent.id}`}
                className="group flex flex-1 flex-col rounded-2xl p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
                style={{
                  background: '#FBF6E8',
                  border: '1px solid rgba(231,198,90,0.24)',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
                }}
              >
                <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Coming up
                </p>
                <div className="flex flex-1 items-start gap-3">
                  <div
                    className="min-w-[40px] shrink-0 rounded-xl p-2 text-center"
                    style={{ background: 'rgba(231,198,90,0.14)' }}
                  >
                    <div className="font-serif text-base leading-none text-navy-900">
                      {nextEventDate.day}
                    </div>
                    <div
                      className="mt-0.5 text-[9px] font-bold uppercase tracking-wider"
                      style={{ color: '#9A7A18' }}
                    >
                      {nextEventDate.month}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <p className="line-clamp-2 text-[13px] font-medium leading-snug text-navy-900 transition-colors group-hover:text-teal-700">
                      {nextEvent.title}
                    </p>
                    <p className="mt-0.5 text-[11px] text-slate-400">{nextEventDate.time} UTC</p>
                  </div>
                </div>
                <span className="mt-auto pt-3 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                  View details →
                </span>
              </Link>
            ) : (
              <div
                className="flex flex-1 flex-col rounded-2xl p-5"
                style={{
                  background: '#FBF6E8',
                  border: '1px solid rgba(231,198,90,0.22)',
                }}
              >
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Coming up
                </p>
                <p className="flex-1 text-[13px] leading-relaxed text-slate-400">
                  No upcoming sessions yet.
                </p>
              </div>
            )}

            {/* Community — pale blue-grey */}
            {recentPosts[0] ? (
              <Link
                href={`/spaces/${slug}/community/${recentPosts[0].id}`}
                className="group flex flex-1 flex-col rounded-2xl p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
                style={{
                  background: '#EEF2F5',
                  border: '1px solid rgba(148,163,184,0.24)',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
                }}
              >
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
                  Community
                </p>
                {recentPosts[0].title ? (
                  <p className="flex-1 font-serif text-[13px] leading-snug text-navy-900 transition-colors group-hover:text-teal-700">
                    {recentPosts[0].title}
                  </p>
                ) : (
                  <p className="flex-1 line-clamp-2 text-[12px] leading-relaxed text-slate-600">
                    {recentPosts[0].body.split('\n\n')[0]}
                  </p>
                )}
                <span className="mt-auto pt-3 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                  Join the conversation →
                </span>
              </Link>
            ) : (
              <Link
                href={`/spaces/${slug}/community`}
                className="group flex flex-1 flex-col rounded-2xl p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
                style={{
                  background: '#EEF2F5',
                  border: '1px solid rgba(148,163,184,0.24)',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
                }}
              >
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
                  Community
                </p>
                <p className="flex-1 font-serif text-[13px] text-navy-900">
                  The conversation begins with you.
                </p>
                <span className="mt-auto pt-3 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                  Open community →
                </span>
              </Link>
            )}
          </div>
        </div>
      </section>

      {/* ── Pathways shelf — no divider, just spacing ── */}
      {activePathways.length > 0 && (
        <section className="mb-10">
          <div className="mb-4 flex items-center justify-between">
            <GoldLabel variant="teal">Pathways</GoldLabel>
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
      )}

      {/* ── Live layer: events + community in one shared band ── */}
      <section className="mb-12">
        <div
          className="overflow-hidden rounded-2xl bg-white px-6 py-7 md:px-8"
          style={{ border: '1px solid rgba(56,160,158,0.12)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
        >
          <GoldLabel variant="teal" className="mb-5">Live + Community</GoldLabel>
          <div className="grid gap-8 lg:grid-cols-2">

            {/* Live experiences column */}
            <div>
              <div className="mb-3 flex items-baseline justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                  Live experiences
                </p>
                <Link
                  href={`/spaces/${slug}/events`}
                  className="text-xs text-teal-600 hover:underline"
                >
                  View all →
                </Link>
              </div>
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
                <div className="rounded-2xl bg-white px-5 py-5 shadow-sm">
                  <p className="mb-1 font-serif text-base text-navy-700">
                    Nothing scheduled yet.
                  </p>
                  <p className="text-sm text-slate-400">
                    Live calls and gatherings will appear here. Come back soon.
                  </p>
                </div>
              )}
            </div>

            {/* Community column */}
            <div>
              <div className="mb-3 flex items-baseline justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                  Community
                </p>
                <Link
                  href={`/spaces/${slug}/community`}
                  className="text-xs text-teal-600 hover:underline"
                >
                  Open →
                </Link>
              </div>
              {recentPosts.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {recentPosts.map((post) => (
                    <Link
                      key={post.id}
                      href={`/spaces/${slug}/community/${post.id}`}
                      className="group block rounded-2xl bg-white px-5 py-4 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
                    >
                      {post.title ? (
                        <p className="mb-1 font-serif text-sm leading-snug text-navy-800 transition-colors group-hover:text-teal-700">
                          {post.title}
                        </p>
                      ) : (
                        <p className="mb-1 line-clamp-2 text-sm leading-relaxed text-navy-800 transition-colors group-hover:text-teal-700">
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
                <div className="rounded-2xl bg-white px-5 py-6 shadow-sm">
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
            </div>
          </div>
        </div>
      </section>

      {/* ── Closing note — soft pale cream card, grounding moment ── */}
      <section>
        <div
          className="max-w-xl rounded-2xl px-7 py-8"
          style={{
            background: '#FBF6E8',
            border: '1px solid rgba(231,198,90,0.22)',
          }}
        >
          <div
            className="mb-3 h-[2px] w-6 rounded-full"
            style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
          />
          <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            A note
          </p>
          <p className="font-serif text-xl text-navy-900">
            You are in the right place.
          </p>
          <p className="mt-2 text-[14px] leading-relaxed text-slate-500">
            This space is designed to grow with you. Start with the REAL Journey,
            return often, and let the structure hold you. Nothing here is about
            speed or perfection.
          </p>
        </div>
      </section>

    </div>
  )
}
