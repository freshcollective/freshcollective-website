import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorPathways, getCreatorEvents } from '@/lib/serverApi'
import type { CreatorPathway, CreatorEvent } from '@/types/platform'

type StepStatus = 'not_started' | 'in_progress' | 'complete'

const STATUS_CONFIG: Record<StepStatus, { label: string; bg: string; color: string }> = {
  complete:    { label: 'Complete',    bg: 'rgba(56,160,158,0.10)',  color: '#38A09E' },
  in_progress: { label: 'In progress', bg: 'rgba(212,176,72,0.12)', color: '#b08d2a' },
  not_started: { label: 'Not started', bg: 'rgba(0,0,0,0.05)',      color: '#94a3b8' },
}

export default async function SetupPage() {
  const primarySpace = await getActiveCreatorSpace()

  const [pathways, events]: [CreatorPathway[], CreatorEvent[]] = primarySpace
    ? await Promise.all([
        getCreatorPathways(primarySpace.slug),
        getCreatorEvents(primarySpace.slug),
      ])
    : [[], []]

  const hasStepContent = pathways.some((p) => p.step_count > 0)

  const checklist: {
    label: string
    desc: string
    status: StepStatus
    href: string
  }[] = [
    {
      label: 'Create your collective',
      desc: 'Set the name, tagline, description, and who it is for.',
      status: primarySpace ? 'complete' : 'not_started',
      href: '/creator-studio/create',
    },
    {
      label: 'Shape your first pathway',
      desc: 'Turn your ideas into a sequence people can move through.',
      status: pathways.length > 0 ? 'complete' : primarySpace ? 'in_progress' : 'not_started',
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}/pathways` : '/creator',
    },
    {
      label: 'Add your first step',
      desc: 'Add text, video, reflection, or practice to begin the experience.',
      status: hasStepContent
        ? 'complete'
        : pathways.length > 0
        ? 'in_progress'
        : 'not_started',
      href:
        primarySpace && pathways[0]
          ? `/creator/spaces/${primarySpace.slug}/pathways/${pathways[0].slug}`
          : primarySpace
          ? `/creator/spaces/${primarySpace.slug}/pathways`
          : '/creator',
    },
    {
      label: 'Schedule your first gathering',
      desc: 'Create a live touchpoint, session, circle, workshop, or conversation.',
      status: events.length > 0 ? 'complete' : primarySpace ? 'in_progress' : 'not_started',
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}/events/new` : '/creator',
    },
    {
      label: 'Publish your collective',
      desc: 'Open the doors when it is ready enough to hold people.',
      status:
        primarySpace?.status === 'active'
          ? 'complete'
          : primarySpace
          ? 'in_progress'
          : 'not_started',
      href: primarySpace ? `/creator/spaces/${primarySpace.slug}` : '/creator',
    },
  ]

  const doneCount = checklist.filter((c) => c.status === 'complete').length

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">
          Set up your collective.
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Start with the foundations, then build the rhythm around your work.
        </p>
        <p className="mt-1.5 text-[13px] text-slate-400">
          {doneCount} of {checklist.length} complete
        </p>
      </div>

      <div className="space-y-3">
        {checklist.map(({ label, desc, status, href }, i) => {
          const cfg = STATUS_CONFIG[status]
          return (
            <div
              key={label}
              className="flex items-start gap-4 rounded-2xl border bg-white p-5"
              style={{
                borderColor:
                  status === 'complete'
                    ? 'rgba(56,160,158,0.22)'
                    : status === 'in_progress'
                    ? 'rgba(212,176,72,0.20)'
                    : '#e2e8f0',
              }}
            >
              {/* Step number / check */}
              <div
                className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                style={{
                  background:
                    status === 'complete' ? 'rgba(56,160,158,0.12)' : 'rgba(0,0,0,0.05)',
                  color: status === 'complete' ? '#38A09E' : '#94a3b8',
                  border:
                    status === 'complete'
                      ? '1.5px solid rgba(56,160,158,0.40)'
                      : '1.5px solid rgba(0,0,0,0.12)',
                }}
              >
                {status === 'complete' ? (
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
                <div className="mb-1.5 flex flex-wrap items-center gap-2.5">
                  <p className="text-[15px] font-medium text-navy-900">{label}</p>
                  <span
                    className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                    style={{ background: cfg.bg, color: cfg.color }}
                  >
                    {cfg.label}
                  </span>
                </div>
                <p className="text-[13.5px] leading-relaxed text-slate-500">{desc}</p>
                {status !== 'complete' && (
                  <Link
                    href={href}
                    className="mt-3 inline-block text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
                  >
                    {status === 'in_progress' ? 'Continue →' : 'Start this step →'}
                  </Link>
                )}
              </div>
            </div>
          )
        })}
      </div>

    </div>
  )
}
