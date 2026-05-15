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

      {/* ── Your Journey — dark editorial outer section with three inner dark cards ── */}
      <section className="mb-10">
        <div
          className="overflow-hidden rounded-2xl px-6 py-7 md:px-8 md:py-8"
          style={{
            background:
              'radial-gradient(rgba(66,199,198,0.07) 1px, transparent 1px), ' +
              'radial-gradient(ellipse at 75% 15%, rgba(66,199,198,0.18), transparent 50%), ' +
              'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0D4E4C 100%)',
            backgroundSize: '22px 22px, auto, auto',
          }}
        >
          {/* Section header */}
          <div className="mb-5 flex items-center gap-2.5">
            <div
              className="h-[2px] w-4 shrink-0 rounded-full"
              style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
            />
            <span
              className="text-[10px] font-semibold uppercase tracking-[0.16em]"
              style={{ color: '#42C7C6' }}
            >
              Your journey
            </span>
          </div>

          <div className="grid gap-3 lg:grid-cols-3">

            {/* Continue inner dark card — 2/3 width */}
            <div className="lg:col-span-2">
              <ContinueCard
                data={continueData}
                progressPct={progressPct}
                stepCount={continuedPathway?.step_count ?? 0}
                completedCount={continuedPathway?.completed_count ?? 0}
              />
            </div>

            {/* Right column — Coming Up + Community inner dark cards */}
            <div className="flex flex-col gap-3">

              {/* Coming up inner dark card */}
              {nextEvent && nextEventDate ? (
                <Link
                  href={`/spaces/${slug}/events/${nextEvent.id}`}
                  className="group flex flex-1 flex-col overflow-hidden rounded-xl transition-all hover:brightness-110"
                  style={{
                    background: 'rgba(255,255,255,0.10)',
                    border: '1px solid rgba(255,255,255,0.14)',
                  }}
                >
                  <div
                    className="h-[3px] w-full"
                    style={{ background: 'linear-gradient(90deg, rgba(231,198,90,0.85) 0%, rgba(231,198,90,0.3) 60%, transparent 100%)' }}
                  />
                  <div className="flex flex-1 flex-col p-4">
                    <p
                      className="mb-2.5 text-[10px] font-bold uppercase tracking-[0.14em]"
                      style={{ color: 'rgba(231,198,90,0.85)' }}
                    >
                      Coming up
                    </p>
                    <div className="flex flex-1 items-start gap-3">
                      <div
                        className="min-w-[38px] shrink-0 rounded-lg p-1.5 text-center"
                        style={{ background: 'rgba(231,198,90,0.15)' }}
                      >
                        <div className="font-serif text-base leading-none" style={{ color: '#FFFFFF' }}>
                          {nextEventDate.day}
                        </div>
                        <div
                          className="mt-0.5 text-[9px] font-bold uppercase tracking-wider"
                          style={{ color: 'rgba(231,198,90,0.75)' }}
                        >
                          {nextEventDate.month}
                        </div>
                      </div>
                      <div className="min-w-0">
                        <p
                          className="line-clamp-2 text-[13px] font-medium leading-snug transition-opacity group-hover:opacity-80"
                          style={{ color: '#FFFFFF' }}
                        >
                          {nextEvent.title}
                        </p>
                        <p className="mt-0.5 text-[11px]" style={{ color: 'rgba(255,255,255,0.45)' }}>
                          {nextEventDate.time} UTC
                        </p>
                      </div>
                    </div>
                    <span
                      className="mt-3 text-[12px] font-semibold transition-opacity group-hover:opacity-80"
                      style={{ color: '#6DD9D8' }}
                    >
                      View details →
                    </span>
                  </div>
                </Link>
              ) : (
                <div
                  className="flex flex-1 flex-col overflow-hidden rounded-xl"
                  style={{
                    background: 'rgba(255,255,255,0.07)',
                    border: '1px solid rgba(255,255,255,0.10)',
                  }}
                >
                  <div
                    className="h-[3px] w-full"
                    style={{ background: 'linear-gradient(90deg, rgba(231,198,90,0.6) 0%, transparent 100%)' }}
                  />
                  <div className="flex flex-1 flex-col p-4">
                    <p
                      className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em]"
                      style={{ color: 'rgba(231,198,90,0.70)' }}
                    >
                      Coming up
                    </p>
                    <p className="flex-1 text-[13px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.45)' }}>
                      No upcoming sessions yet.
                    </p>
                  </div>
                </div>
              )}

              {/* Community inner dark card */}
              {recentPosts[0] ? (
                <Link
                  href={`/spaces/${slug}/community/${recentPosts[0].id}`}
                  className="group flex flex-1 flex-col overflow-hidden rounded-xl transition-all hover:brightness-110"
                  style={{
                    background: 'rgba(255,255,255,0.10)',
                    border: '1px solid rgba(255,255,255,0.14)',
                  }}
                >
                  <div
                    className="h-[3px] w-full"
                    style={{ background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 60%, transparent 100%)' }}
                  />
                  <div className="flex flex-1 flex-col p-4">
                    <p
                      className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em]"
                      style={{ color: '#6DD9D8' }}
                    >
                      Community
                    </p>
                    {recentPosts[0].title ? (
                      <p
                        className="flex-1 font-serif text-[13px] leading-snug transition-opacity group-hover:opacity-80"
                        style={{ color: '#FFFFFF' }}
                      >
                        {recentPosts[0].title}
                      </p>
                    ) : (
                      <p
                        className="flex-1 line-clamp-2 text-[12px] leading-relaxed"
                        style={{ color: 'rgba(255,255,255,0.72)' }}
                      >
                        {recentPosts[0].body.split('\n\n')[0]}
                      </p>
                    )}
                    <span
                      className="mt-3 text-[12px] font-semibold transition-opacity group-hover:opacity-80"
                      style={{ color: '#6DD9D8' }}
                    >
                      Join the conversation →
                    </span>
                  </div>
                </Link>
              ) : (
                <Link
                  href={`/spaces/${slug}/community`}
                  className="group flex flex-1 flex-col overflow-hidden rounded-xl transition-all hover:brightness-110"
                  style={{
                    background: 'rgba(255,255,255,0.10)',
                    border: '1px solid rgba(255,255,255,0.14)',
                  }}
                >
                  <div
                    className="h-[3px] w-full"
                    style={{ background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 60%, transparent 100%)' }}
                  />
                  <div className="flex flex-1 flex-col p-4">
                    <p
                      className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em]"
                      style={{ color: '#6DD9D8' }}
                    >
                      Community
                    </p>
                    <p
                      className="flex-1 font-serif text-[13px]"
                      style={{ color: 'rgba(255,255,255,0.72)' }}
                    >
                      The conversation begins with you.
                    </p>
                    <span
                      className="mt-3 text-[12px] font-semibold transition-opacity group-hover:opacity-80"
                      style={{ color: '#6DD9D8' }}
                    >
                      Open community →
                    </span>
                  </div>
                </Link>
              )}
            </div>
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
          className="overflow-hidden rounded-2xl px-6 py-7 md:px-8"
          style={{
            background:
              'radial-gradient(rgba(56,160,158,0.06) 1px, transparent 1px), ' +
              'linear-gradient(135deg, rgba(234,248,247,0.82) 0%, rgba(240,251,250,0.92) 55%, rgba(252,252,250,0.96) 100%)',
            backgroundSize: '20px 20px, auto',
            border: '1px solid rgba(56,160,158,0.12)',
          }}
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

      {/* ── Closing note — narrower, more of a grounding moment than a block ── */}
      <section>
        <div
          className="max-w-xl overflow-hidden rounded-2xl px-7 py-9"
          style={{
            background:
              'radial-gradient(rgba(66,199,198,0.06) 1px, transparent 1px), ' +
              'radial-gradient(ellipse at 80% 20%, rgba(66,199,198,0.18), transparent 45%), ' +
              'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0F5E5C 100%)',
            backgroundSize: '22px 22px, auto, auto',
          }}
        >
          <div
            className="mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
          />
          <p
            className="mb-0.5 text-[10px] font-bold uppercase tracking-[0.18em]"
            style={{ color: '#42C7C6' }}
          >
            A note
          </p>
          <p className="font-serif text-xl" style={{ color: '#FFFFFF' }}>
            You are in the right place.
          </p>
          <p
            className="mt-2 text-[14px] leading-relaxed"
            style={{ color: 'rgba(255,255,255,0.65)' }}
          >
            This space is designed to grow with you. Start with the REAL Journey,
            return often, and let the structure hold you. Nothing here is about
            speed or perfection.
          </p>
        </div>
      </section>

    </div>
  )
}
