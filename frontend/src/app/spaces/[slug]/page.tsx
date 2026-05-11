import Link from 'next/link'
import {
  getContinue,
  getSpacePathwaysProgress,
  getSpaceEvents,
} from '@/lib/serverApi'
import ContinueCard from '@/components/spaces/ContinueCard'
import PathwayProgressCard from '@/components/spaces/PathwayProgressCard'
import EventCard from '@/components/spaces/EventCard'
import type { PathwayProgress, EventSummary, ContinueResponse } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-4 text-xs font-medium uppercase tracking-widest text-gold-700">
      {children}
    </p>
  )
}

function Divider() {
  return <div className="my-12 h-px bg-border" />
}

export default async function SpacePage({ params }: Props) {
  const { slug } = await params

  const [pathwaysProgress, events, continueData]: [
    PathwayProgress[],
    EventSummary[],
    ContinueResponse | null,
  ] = await Promise.all([
    getSpacePathwaysProgress(slug),
    getSpaceEvents(slug),
    getContinue(),
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

  return (
    <div className="pb-16">

      {/* ── Continue Your Journey ─────────────────────────────────── */}
      <section className="mb-12">
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
          <section className="mb-12">
            <div className="mb-5 flex items-baseline justify-between">
              <SectionLabel>Pathways</SectionLabel>
              <Link
                href={`/spaces/${slug}/pathways`}
                className="text-sm text-teal-600 hover:underline"
              >
                Browse all
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
          <SectionLabel>Coming up</SectionLabel>
          {events.length > 0 ? (
            <div className="flex flex-col gap-3">
              {events.map((e) => (
                <EventCard key={e.id} event={e} spaceSlug={slug} />
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-surface p-6">
              <p className="mb-1 font-serif text-base text-navy-700">
                No upcoming sessions yet.
              </p>
              <p className="text-sm text-slate-400">
                Live calls, workshops, and gatherings will appear here when scheduled.
              </p>
            </div>
          )}
        </section>

        {/* Community Snapshot */}
        <section>
          <SectionLabel>In the community</SectionLabel>
          <div className="flex flex-col gap-3">

            <div className="rounded-xl border border-border bg-surface px-5 py-4">
              <p className="mb-1 text-xs font-medium text-teal-700 uppercase tracking-wider">
                This week's reflection
              </p>
              <p className="font-serif text-base text-navy-800 leading-snug">
                What pattern are you noticing most clearly right now?
              </p>
              <Link
                href={`/spaces/${slug}/community`}
                className="mt-2 inline-block text-xs text-slate-400 hover:text-teal-600"
              >
                Share your reflection →
              </Link>
            </div>

            <div className="rounded-xl border border-border bg-surface px-5 py-4">
              <p className="mb-1 text-xs font-medium text-slate-400 uppercase tracking-wider">
                Members exploring
              </p>
              <p className="text-sm leading-relaxed text-slate-500">
                Growth, alignment, and what feels most alive right now.
              </p>
              <Link
                href={`/spaces/${slug}/community`}
                className="mt-2 inline-block text-xs text-slate-400 hover:text-teal-600"
              >
                Join the conversation →
              </Link>
            </div>

          </div>
        </section>
      </div>

      {/* ── Announcements ────────────────────────────────────────── */}
      <Divider />
      <section>
        <SectionLabel>From Fresh Collective</SectionLabel>
        <div
          className="rounded-xl border border-gold-200 bg-gold-50/40 px-6 py-5"
        >
          <p className="mb-0.5 text-xs font-medium text-gold-700 uppercase tracking-wider">
            Welcome
          </p>
          <p className="font-serif text-lg text-navy-900">
            You are in the right place.
          </p>
          <p className="mt-2 text-sm leading-relaxed text-slate-500 max-w-prose">
            This space is designed to grow with you. Start with the REAL Journey,
            return often, and let the structure hold you. Nothing here is about
            speed or perfection.
          </p>
        </div>
      </section>

    </div>
  )
}
