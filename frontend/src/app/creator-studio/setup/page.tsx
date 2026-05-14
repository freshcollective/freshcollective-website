import Link from 'next/link'
import { getCreatorSpaces, getCreatorPathways, getCreatorEvents } from '@/lib/serverApi'
import type { CreatorPathway, CreatorEvent } from '@/types/platform'

export default async function SetupPage() {
  const spaces = await getCreatorSpaces()
  const primarySpace = spaces[0] ?? null

  const [pathways, events]: [CreatorPathway[], CreatorEvent[]] = primarySpace
    ? await Promise.all([
        getCreatorPathways(primarySpace.slug),
        getCreatorEvents(primarySpace.slug),
      ])
    : [[], []]

  const hasStepContent = pathways.some((p) => p.step_count > 0)

  const checklist = [
    {
      label: 'Create your space',
      desc: 'Set up your collective name, tagline, and description.',
      done: !!primarySpace,
      href: '/creator',
    },
    {
      label: 'Build your first pathway',
      desc: 'A pathway is a structured sequence of steps — your curriculum.',
      done: pathways.length > 0,
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}/pathways` : '/creator',
    },
    {
      label: 'Add content to a step',
      desc: 'Add text, video, reflections, or exercises to your first step.',
      done: hasStepContent,
      href:
        primarySpace && pathways[0]
          ? `/creator/spaces/${primarySpace.slug}/pathways/${pathways[0].slug}`
          : primarySpace
          ? `/creator/spaces/${primarySpace.slug}/pathways`
          : '/creator',
    },
    {
      label: 'Schedule your first gathering',
      desc: 'Live connection is central to Fresh Collective. Add a Zoom call or in-person event.',
      done: events.length > 0,
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}/events/new` : '/creator',
    },
    {
      label: 'Publish your space',
      desc: 'Make your collective visible and open for members to join.',
      done: primarySpace?.status === 'active',
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}` : '/creator',
    },
  ]

  const doneCount = checklist.filter((c) => c.done).length

  return (
    <div className="max-w-3xl px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Setup</h1>
        <p className="mt-2 text-sm text-slate-400">
          {doneCount === checklist.length
            ? 'Everything is set up. Your collective is ready.'
            : `${doneCount} of ${checklist.length} steps complete.`}
        </p>
      </div>

      <div className="space-y-3">
        {checklist.map(({ label, desc, done, href }, i) => (
          <div
            key={label}
            className="flex items-start gap-4 rounded-xl border bg-white p-5"
            style={{ borderColor: done ? 'rgba(56,160,158,0.22)' : '#e2e8f0' }}
          >
            <div
              className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
              style={{
                background: done ? 'rgba(56,160,158,0.12)' : 'rgba(0,0,0,0.05)',
                color: done ? '#38A09E' : '#94a3b8',
                border: done
                  ? '1.5px solid rgba(56,160,158,0.40)'
                  : '1.5px solid rgba(0,0,0,0.12)',
              }}
            >
              {done ? (
                <svg width="8" height="6" viewBox="0 0 8 6" fill="none" aria-hidden="true">
                  <path
                    d="M1 3l2 2 4-4"
                    stroke="#38A09E"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : (
                String(i + 1)
              )}
            </div>
            <div className="flex-1">
              <p className="text-[14px] font-medium text-navy-900">{label}</p>
              <p className="mt-0.5 text-[12.5px] leading-relaxed text-slate-400">{desc}</p>
              {!done && (
                <Link
                  href={href}
                  className="mt-3 inline-block text-[12.5px] font-medium text-teal-600 transition-colors hover:text-teal-700"
                >
                  Start this step →
                </Link>
              )}
            </div>
          </div>
        ))}
      </div>

    </div>
  )
}
