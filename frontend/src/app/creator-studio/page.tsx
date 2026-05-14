import Link from 'next/link'
import { getCreatorSpaces, getCreatorPathways, getCreatorEvents } from '@/lib/serverApi'
import type { CreatorPathway, CreatorEvent } from '@/types/platform'

export default async function CreatorStudioOverviewPage() {
  const spaces = await getCreatorSpaces()
  const primarySpace = spaces[0] ?? null

  const [pathways, events]: [CreatorPathway[], CreatorEvent[]] = primarySpace
    ? await Promise.all([
        getCreatorPathways(primarySpace.slug),
        getCreatorEvents(primarySpace.slug),
      ])
    : [[], []]

  const now = new Date()
  const upcoming = events.filter((e) => new Date(e.starts_at) > now)
  const activePathways = pathways.filter((p) => p.status === 'active')

  const checklist = [
    {
      label: 'Space created',
      done: !!primarySpace,
      href: '/creator',
    },
    {
      label: 'First pathway added',
      done: pathways.length > 0,
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}/pathways` : '/creator',
    },
    {
      label: 'First gathering scheduled',
      done: events.length > 0,
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}/events/new` : '/creator',
    },
    {
      label: 'Space published',
      done: primarySpace?.status === 'active',
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}` : '/creator',
    },
  ]

  const allDone = checklist.every((c) => c.done)

  return (
    <div className="max-w-4xl px-8 py-8 md:px-10 md:py-10">

      {/* Header */}
      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">
          {primarySpace ? primarySpace.name : 'Your Studio'}
        </h1>
        {primarySpace?.tagline && (
          <p className="mt-1.5 text-sm text-slate-400">{primarySpace.tagline}</p>
        )}
      </div>

      {/* No space yet */}
      {!primarySpace && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 font-serif text-lg text-navy-900">Create your collective</p>
          <p className="mb-5 text-sm text-slate-400">
            You haven't set up a space yet. Head to the creator area to get started.
          </p>
          <Link
            href="/creator"
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Go to creator area →
          </Link>
        </div>
      )}

      {primarySpace && (
        <>
          {/* Stats */}
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Pathways', value: pathways.length },
              { label: 'Published', value: activePathways.length },
              { label: 'Gatherings', value: events.length },
              { label: 'Upcoming', value: upcoming.length },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-xl border border-border bg-white p-4">
                <p className="font-serif text-2xl text-navy-900">{value}</p>
                <p className="mt-0.5 text-[12px] text-slate-400">{label}</p>
              </div>
            ))}
          </div>

          {/* Setup checklist */}
          {!allDone && (
            <div className="mb-6 rounded-xl border border-border bg-white p-6">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="font-serif text-base text-navy-900">Getting started</h2>
                <span className="text-[12px] text-slate-400">
                  {checklist.filter((c) => c.done).length}/{checklist.length} complete
                </span>
              </div>
              <ul className="space-y-3">
                {checklist.map(({ label, done, href }) => (
                  <li key={label} className="flex items-center gap-3">
                    <div
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                      style={{
                        background: done ? 'rgba(56,160,158,0.12)' : 'rgba(0,0,0,0.05)',
                        border: done
                          ? '1.5px solid rgba(56,160,158,0.40)'
                          : '1.5px solid rgba(0,0,0,0.12)',
                      }}
                    >
                      {done && (
                        <svg width="8" height="6" viewBox="0 0 8 6" fill="none" aria-hidden="true">
                          <path
                            d="M1 3l2 2 4-4"
                            stroke="#38A09E"
                            strokeWidth="1.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      )}
                    </div>
                    <span
                      className="flex-1 text-[13.5px]"
                      style={{ color: done ? 'rgba(0,0,0,0.38)' : '#1e293b' }}
                    >
                      {label}
                    </span>
                    {!done && (
                      <Link
                        href={href}
                        className="text-[12px] font-medium text-teal-600 transition-colors hover:text-teal-700"
                      >
                        Do this →
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Quick actions */}
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              {
                label: 'Manage pathways',
                desc: `${pathways.length} pathway${pathways.length !== 1 ? 's' : ''}`,
                href: `/creator/spaces/${primarySpace.slug}/pathways`,
              },
              {
                label: 'Schedule gathering',
                desc: upcoming.length > 0 ? `${upcoming.length} coming up` : 'No upcoming events',
                href: `/creator/spaces/${primarySpace.slug}/events/new`,
              },
              {
                label: 'View community',
                desc: 'Posts and discussions',
                href: `/creator/spaces/${primarySpace.slug}/community`,
              },
            ].map(({ label, desc, href }) => (
              <Link
                key={href}
                href={href}
                className="group rounded-xl border border-border bg-white p-5 transition-all hover:border-teal-200 hover:shadow-sm"
              >
                <p className="text-[14px] font-medium text-navy-900 transition-colors group-hover:text-teal-700">
                  {label}
                </p>
                <p className="mt-1 text-[12px] text-slate-400">{desc}</p>
              </Link>
            ))}
          </div>
        </>
      )}

    </div>
  )
}
