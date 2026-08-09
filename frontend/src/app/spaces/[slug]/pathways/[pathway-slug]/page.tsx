import { notFound, redirect } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview, getMyPasses, getKnowledgeGuide, getSpace } from '@/lib/serverApi'
import PathwayAutoRevalidate from '@/components/spaces/PathwayAutoRevalidate'
import KnowledgeGuideView from '@/components/spaces/KnowledgeGuideView'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import type {
  PathwayWithSteps,
  StepSummary,
  AccessPassSummary,
  KnowledgeGuide,
} from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
  searchParams: Promise<Record<string, string | string[] | undefined>>
}

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text: 'Read',
  reflection: 'Reflect',
  exercise: 'Exercise',
  video: 'Watch',
  audio: 'Listen',
}

function StepRow({
  step,
  spaceSlug,
  pathwaySlug,
  index,
}: {
  step: StepSummary
  spaceSlug: string
  pathwaySlug: string
  index: number
}) {
  const href = `/spaces/${spaceSlug}/pathways/${pathwaySlug}/${step.slug}`
  const locked = step.availability?.is_locked === true
  const lockMessage = step.availability?.message ?? null

  const inner = (
    <>
      <div
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
        style={step.is_completed
          ? { background: 'var(--fc-accent, #14b8a6)', color: '#FFFFFF' }
          : locked
            ? { background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.55)' }
            : { background: 'var(--fc-accent-soft, #f0fdfa)', color: 'var(--fc-accent, #0d9488)' }}
      >
        {step.is_completed ? '✓' : locked ? '🔒' : index + 1}
      </div>

      <div className="min-w-0 flex-1">
        <p
          className="font-medium leading-snug"
          style={step.is_completed
            ? { color: 'var(--fc-accent, #0f766e)' }
            : locked
              ? { color: 'rgba(12,24,38,0.55)' }
              : { color: '#0C1826' }}
        >
          {step.title}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-black">
          <span>{CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type}</span>
          {step.estimated_minutes && <span>{step.estimated_minutes} min</span>}
          {locked && lockMessage && (
            <span style={{ color: 'rgba(12,24,38,0.62)' }}>{lockMessage}</span>
          )}
        </div>
      </div>

      {!locked && (
        <span className="shrink-0 self-center text-black transition-colors group-hover:text-teal-500">
          →
        </span>
      )}
    </>
  )

  if (locked) {
    // Locked steps stay visible in the list — the release system is a
    // gate, not a hide — but the row is not interactive.
    return (
      <div
        className="flex items-start gap-4 rounded-2xl border px-5 py-4"
        style={{ borderColor: 'rgba(12,24,38,0.08)', background: 'rgba(12,24,38,0.02)' }}
        aria-disabled="true"
      >
        {inner}
      </div>
    )
  }

  return (
    <Link
      href={href}
      className={[
        'group flex items-start gap-4 rounded-2xl border px-5 py-4 transition-all hover:-translate-y-0.5 hover:shadow-sm',
        step.is_completed
          ? 'border-teal-200 bg-teal-50/40 hover:border-teal-300'
          : 'border-border bg-white hover:border-teal-200',
      ].join(' ')}
    >
      {inner}
    </Link>
  )
}

function PassWidget({ pass, spaceSlug }: { pass: AccessPassSummary; spaceSlug: string }) {
  const validUntil = pass.valid_until
    ? new Date(pass.valid_until).toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })
    : null
  const remaining = pass.remaining_credits ?? 0
  const total = pass.total_credits
  const exhausted = total !== null && remaining <= 0

  return (
    <div
      className="mb-6 rounded-2xl border p-5"
      style={{ borderColor: 'rgba(56,160,158,0.25)', background: 'rgba(56,160,158,0.04)' }}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-semibold text-teal-700">
            Your EMBODY pass — {pass.option_name ?? 'Term Pass'}
          </p>
          <p className="mt-0.5 text-[12px] text-black">
            {pass.credits_per_week ? `${pass.credits_per_week} session${pass.credits_per_week !== 1 ? 's' : ''} per week` : 'Active'}
            {validUntil && ` · valid until ${validUntil}`}
          </p>
        </div>
        <span
          className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          style={{ background: 'rgba(56,160,158,0.12)', color: '#0f766e' }}
        >
          Active
        </span>
      </div>

      {total !== null && (
        <div className="mb-3">
          <div className="space-y-1 mb-2">
            <div className="flex items-center justify-between text-[12px]">
              <span className="text-black">Sessions included</span>
              <span className="font-semibold text-navy-900">{total}</span>
            </div>
            <div className="flex items-center justify-between text-[12px]">
              <span className="text-black">Booked</span>
              <span className="font-semibold text-navy-900">{pass.used_credits}</span>
            </div>
            <div className="flex items-center justify-between text-[12px]">
              <span className="text-black">Available to book</span>
              <span className={`font-semibold ${remaining > 0 ? 'text-teal-700' : 'text-black'}`}>{remaining}</span>
            </div>
          </div>
          <div
            className="h-1.5 w-full overflow-hidden rounded-full"
            style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))' }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${total > 0 ? Math.round((pass.used_credits / total) * 100) : 0}%` }}
            />
          </div>
          {exhausted ? (
            <p className="mt-2 text-[12px] leading-relaxed text-black">
              All included sessions are booked for this term. Message Lindsey if you need help changing a session.
            </p>
          ) : (
            <p className="mt-2 text-[12px] leading-relaxed text-teal-600/80">
              Need help booking? Message Lindsey and she can book your regular sessions for you.
            </p>
          )}
        </div>
      )}

      {!exhausted && (
        <Link
          href={`/spaces/${spaceSlug}/events`}
          className="inline-block rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
        >
          Book sessions →
        </Link>
      )}
    </div>
  )
}

function SuccessBanner({ pass, spaceSlug, pathwaySlug }: { pass: AccessPassSummary | null; spaceSlug: string; pathwaySlug: string }) {
  const optionName = pass?.option_name ?? 'EMBODY pass'
  const remaining = pass?.remaining_credits ?? pass?.total_credits ?? null

  return (
    <div
      className="mb-6 rounded-2xl border p-6"
      style={{ borderColor: 'rgba(56,160,158,0.30)', background: 'rgba(56,160,158,0.07)' }}
    >
      <div className="mb-3 flex items-center gap-3">
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[16px]"
          style={{ background: 'rgba(56,160,158,0.15)', color: '#0f766e' }}
        >
          ✓
        </div>
        <div>
          <p className="text-[15px] font-semibold" style={{ color: 'var(--fc-accent, #0f766e)' }}>Your EMBODY pass is active.</p>
          <p className="text-[12px] text-black">{optionName}{remaining !== null ? ` · ${remaining} sessions included` : ''}</p>
        </div>
      </div>

      <p className="mb-4 text-[13px] leading-relaxed text-black">
        <strong>Next step: book your regular sessions.</strong>
        {' '}You can book yourself from the Gatherings page, or message Lindsey with your preferred regular session day/s and she will book your regular sessions for the term.
      </p>

      <div className="flex flex-wrap gap-2">
        <Link
          href={`/spaces/${spaceSlug}/events`}
          className="inline-block rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
        >
          Book sessions →
        </Link>
        <Link
          href={`/spaces/${spaceSlug}/pathways/${pathwaySlug}/how-your-pass-works`}
          className="inline-block rounded-xl border border-teal-200 bg-white px-4 py-2 text-[13px] font-medium text-teal-700 transition-colors hover:bg-teal-50"
        >
          How your pass works
        </Link>
        <Link
          href={`/spaces/${spaceSlug}/pathways/${pathwaySlug}/what-to-bring`}
          className="inline-block rounded-xl border border-slate-200 bg-white px-4 py-2 text-[13px] font-medium text-black transition-colors hover:border-slate-300"
        >
          What to bring
        </Link>
      </div>
    </div>
  )
}

export default async function PathwayDetailPage({ params, searchParams }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params
  const sp = await searchParams
  const isSuccess = sp.success === 'true'

  const pathway: PathwayWithSteps | null = await getPathwayOverview(slug, pathwaySlug)

  if (!pathway) notFound()

  const cs = getPathwayCoverStyle(pathwaySlug)
  const coverImageUrl = resolveMediaUrl(pathway.cover_image_url)
  const isComingSoon = pathway.status === 'coming_soon'
  // Use server-computed user_has_access — covers free, included, paid+entitlement, admin/creator
  const locked = !isComingSoon && !pathway.user_has_access

  // Redirect locked users to the About page (preview/sales page) instead of showing a wall
  if (locked) {
    redirect(`/spaces/${slug}/pathways/${pathwaySlug}/about`)
  }

  // Knowledge Guide branch — this pathway is a continuous reference
  // document. Fetch the full guide payload in one round trip and
  // render inline; skip the Guided Experience redirect-to-first-step
  // logic entirely. No progress, no completion, no next/previous
  // navigation — just the guide.
  if (!isComingSoon && pathway.pathway_type === 'knowledge_guide') {
    const [guide, space]: [
      KnowledgeGuide | null,
      { colour_palette?: CollectivePaletteMeta | null } | null,
    ] = await Promise.all([
      getKnowledgeGuide(slug, pathwaySlug),
      getSpace(slug),
    ])
    if (!guide) notFound()
    return (
      <KnowledgeGuideView
        guide={guide}
        collectivePalette={space?.colour_palette ?? null}
      />
    )
  }

  // For accessible users with steps, skip the overview and go straight to the right step —
  // UNLESS they just completed checkout (?success=true), in which case show the overview with
  // a success banner and pass widget first.
  if (!isComingSoon && pathway.steps.length > 0 && !isSuccess) {
    const nextIncomplete = pathway.steps.find((s) => !s.is_completed)
    const continueSlug = nextIncomplete?.slug ?? pathway.steps[0].slug
    redirect(`/spaces/${slug}/pathways/${pathwaySlug}/${continueSlug}`)
  }

  // Fetch pass data for the success banner / pass widget
  let activePass: AccessPassSummary | null = null
  if (isSuccess || pathway.user_has_access) {
    try {
      const passes = await getMyPasses(slug)
      activePass = passes.find(
        (p) => p.eligible_pathway_id === pathway.id && p.status === 'active'
      ) ?? passes[0] ?? null
    } catch {
      // Non-fatal — widget simply won't show
    }
  }

  const progressPct =
    pathway.step_count > 0
      ? Math.round((pathway.completed_count / pathway.step_count) * 100)
      : 0

  // Collect every known future unlock timestamp so the auto-revalidate
  // component can arm one timer for the nearest one. Only time-based
  // lock types (days_after_enrolment, fixed_date) supply this; the
  // others don't have a known unlock instant.
  const upcomingUnlocks = pathway.steps
    .map((s) => s.availability?.unlocks_at)
    .filter((v): v is string => !!v)

  return (
    <div className="max-w-2xl">
      <PathwayAutoRevalidate upcomingUnlocks={upcomingUnlocks} />
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/pathways`}
          className="text-sm text-black transition-colors hover:text-teal-600"
        >
          ← All Pathways
        </Link>
      </div>

      {/* ── Pathway hero banner ── */}
      <div
        className="relative mb-6 overflow-hidden rounded-2xl"
        style={{
          background: cs.background,
          backgroundSize: cs.backgroundSize ?? 'auto',
        }}
      >
        {/* Uploaded cover image — layers over CSS gradient */}
        {coverImageUrl && (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={coverImageUrl}
              alt=""
              aria-hidden="true"
              className="absolute inset-0 h-full w-full object-cover"
            />
            <div
              className="absolute inset-0"
              style={{
                background:
                  'linear-gradient(135deg, rgba(7,24,36,0.75) 0%, rgba(7,56,58,0.58) 100%)',
              }}
            />
          </>
        )}

        <div className="relative px-7 py-10 md:px-9 md:py-12">
          <div
            className="mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'var(--fc-accent, #2dd4bf)' }}
          />
          <p
            className="mb-1 text-[9px] font-bold uppercase tracking-[0.20em]"
            style={{ color: coverImageUrl ? '#FFFFFF' : cs.labelColor }}
          >
            {isComingSoon ? 'Coming soon' : locked ? 'Pathway' : 'Pathway'}
          </p>
          <h2
            className="font-serif text-2xl md:text-3xl"
            style={{ color: coverImageUrl ? '#FFFFFF' : cs.titleColor }}
          >
            {pathway.title}
          </h2>
          {pathway.description && (
            <p
              className="mt-2.5 max-w-md text-[14px] leading-relaxed"
              style={{ color: (coverImageUrl || cs.isDark) ? '#FFFFFF' : '#000000' }}
            >
              {pathway.description}
            </p>
          )}
        </div>
      </div>

      {/* ── Post-checkout success banner ── */}
      {isSuccess && <SuccessBanner pass={activePass} spaceSlug={slug} pathwaySlug={pathwaySlug} />}

      {/* ── Active pass widget (shown on success view) ── */}
      {isSuccess && activePass && <PassWidget pass={activePass} spaceSlug={slug} />}

      {/* ── Coming soon or accessible pathway view ── */}
      {isComingSoon ? (
        /* ── Coming soon view ── */
        <div className="rounded-2xl border border-teal-100 bg-white p-6 text-sm text-black">
          This pathway is coming soon.
        </div>
      ) : (
        /* ── Accessible pathway view ── */
        <>
          {pathway.step_count > 0 && (
            <div className="mb-8">
              <div className="mb-1.5 flex items-baseline justify-between text-xs text-black">
                <span>{pathway.completed_count} of {pathway.step_count} steps complete</span>
                <span>{progressPct}%</span>
              </div>
              <div
                className="h-1.5 w-full overflow-hidden rounded-full"
                style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))' }}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${progressPct}%`, background: 'var(--fc-accent, #14b8a6)' }}
                />
              </div>
            </div>
          )}

{pathway.steps.length === 0 ? (
            <div className="rounded-2xl border border-teal-100 bg-white p-6 text-sm text-black">
              Steps for this pathway are coming soon.
            </div>
          ) : pathway.sections.length > 0 ? (
            /* Section-grouped view */
            <div className="flex flex-col gap-6">
              {(() => {
                const sectionedIds = new Set(pathway.sections.flatMap((s) => s.steps.map((st) => st.id)))
                const unsectioned = pathway.steps.filter((s) => !sectionedIds.has(s.id))
                let globalIndex = 0
                const groups: React.ReactNode[] = []

                // Sections first (in position order as returned by backend).
                // Section banners are NOT rendered here — they appear above
                // the first step of each section on the member step page.
                pathway.sections.forEach((section) => {
                  groups.push(
                    <div key={section.id}>
                      <p className="mb-3 text-[13px] font-semibold text-black">
                        {section.title}
                      </p>
                      <div className="flex flex-col gap-3">
                        {section.steps.map((step) => {
                          const el = <StepRow key={step.id} step={step} spaceSlug={slug} pathwaySlug={pathwaySlug} index={globalIndex} />
                          globalIndex++
                          return el
                        })}
                      </div>
                    </div>
                  )
                })

                // Unsectioned steps at the bottom
                if (unsectioned.length > 0) {
                  groups.push(
                    <div key="__unsectioned" className="flex flex-col gap-3">
                      {unsectioned.map((step) => {
                        const el = <StepRow key={step.id} step={step} spaceSlug={slug} pathwaySlug={pathwaySlug} index={globalIndex} />
                        globalIndex++
                        return el
                      })}
                    </div>
                  )
                }

                return groups
              })()}
            </div>
          ) : (
            /* Flat list (no sections) */
            <div className="flex flex-col gap-3">
              {pathway.steps.map((step, i) => (
                <StepRow
                  key={step.id}
                  step={step}
                  spaceSlug={slug}
                  pathwaySlug={pathwaySlug}
                  index={i}
                />
              ))}
            </div>
          )}

          {isSuccess && pathway.steps.length > 0 && (
            <div className="mt-6">
              <Link
                href={`/spaces/${slug}/pathways/${pathwaySlug}/${pathway.steps[0].slug}`}
                className="inline-block rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
              >
                Start reading →
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  )
}
