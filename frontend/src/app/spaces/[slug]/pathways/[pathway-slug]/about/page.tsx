import React from 'react'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview, getPathwayAboutBlocks, getSpace } from '@/lib/serverApi'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl, apiUrl } from '@/lib/api'
import { isPathwayLocked, formatPathwayPrice, unlockCtaLabel } from '@/lib/pathwayAccess'
import { AboutBlockRenderer } from '@/components/spaces/AboutBlockRenderer'
import { PlanRecoveryBanner } from '@/components/commerce/PlanRecoveryBanner'
import type { PathwayWithSteps, PathwayAboutBlock, PaymentOptionSummary, SpaceResponse } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
}



export default async function PathwayAboutPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params

  const [pathway, aboutBlocks, space]: [
    PathwayWithSteps | null,
    PathwayAboutBlock[],
    (SpaceResponse & { colour_palette?: CollectivePaletteMeta | null }) | null,
  ] = await Promise.all([
    getPathwayOverview(slug, pathwaySlug),
    getPathwayAboutBlocks(slug, pathwaySlug),
    getSpace(slug),
  ])

  if (!pathway) notFound()

  // Palette-linked block colours (``palette:<role>``) resolve against
  // this space's active palette at render time. Custom hex and legacy
  // fixed keys ignore this and render their stored values verbatim.
  const collectivePalette: CollectivePaletteMeta | null = space?.colour_palette ?? null

  const cs = getPathwayCoverStyle(pathwaySlug)
  const coverImageUrl = resolveMediaUrl(pathway.cover_image_url)
  const isComingSoon = pathway.status === 'coming_soon'
  // Use server-computed user_has_access — covers free, included, paid+entitlement, admin/creator
  const locked = !isComingSoon && !pathway.user_has_access

  const publishedOptions: PaymentOptionSummary[] = pathway.payment_options ?? []
  const isPaymentOptionsMode = pathway.pricing_mode === 'payment_options'

  const lowestOptionPrice = publishedOptions.reduce((min, o) =>
    o.effective_price_cents != null && (min == null || o.effective_price_cents < min)
      ? o.effective_price_cents : min,
    null as number | null)

  const priceLabel = locked
    ? (isPaymentOptionsMode
        ? (lowestOptionPrice != null
            ? `From $${(lowestOptionPrice / 100).toFixed(0)} AUD`
            : publishedOptions.length > 0 ? `${publishedOptions.length} options available` : 'Multiple options')
        : formatPathwayPrice(pathway.price_cents, pathway.currency, pathway.billing_interval))
    : null
  const unlockLabel = locked
    ? (isPaymentOptionsMode ? 'Choose your option' : unlockCtaLabel(pathway.access_type, pathway.price_cents, pathway.currency, pathway.billing_interval))
    : null

  const nextIncomplete = pathway.steps.find(s => !s.is_completed)
  const continueHref = nextIncomplete
    ? `/spaces/${slug}/pathways/${pathwaySlug}/${nextIncomplete.slug}`
    : `/spaces/${slug}/pathways/${pathwaySlug}/${pathway.steps[0]?.slug}`

  const progressPct = pathway.step_count > 0
    ? Math.round((pathway.completed_count / pathway.step_count) * 100)
    : 0

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-6">

      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/pathways`}
          className="text-sm text-black transition-colors hover:text-[color:var(--fc-accent,#0d9488)]"
        >
          ← All Pathways
        </Link>
      </div>

      {/* ── Two-column layout on desktop ── */}
      <div className="grid gap-8 lg:grid-cols-[1fr_300px]">

        {/* ── Main content ── */}
        <div>
          {/* Hero banner */}
          <div
            className="relative mb-7 overflow-hidden rounded-2xl"
            style={{
              background: cs.background,
              backgroundSize: cs.backgroundSize ?? 'auto',
            }}
          >
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
                  style={{ background: 'linear-gradient(135deg, rgba(7,24,36,0.75) 0%, rgba(7,56,58,0.58) 100%)' }}
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
                Pathway
              </p>
              <h1
                className="font-serif text-2xl md:text-3xl"
                style={{ color: coverImageUrl ? '#FFFFFF' : cs.titleColor }}
              >
                {pathway.title}
              </h1>
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

          {/* About blocks */}
          {aboutBlocks.length > 0 ? (
            <div className="space-y-6">
              {aboutBlocks.map(block => (
                <AboutBlockRenderer key={block.id} block={block} collectivePalette={collectivePalette} />
              ))}
            </div>
          ) : (
            /* Fallback when no about blocks exist */
            <div className="space-y-4">
              {pathway.description && (
                <p className="text-[16px] leading-relaxed text-black">{pathway.description}</p>
              )}
              {pathway.step_count > 0 && (
                <p className="text-[14px] text-black">
                  {pathway.step_count} step{pathway.step_count !== 1 ? 's' : ''} in this pathway.
                </p>
              )}
            </div>
          )}
        </div>

        {/* ── Right sidebar ── */}
        <div className="flex flex-col gap-4 lg:sticky lg:top-6 lg:self-start">

          {/* FIP4B1 — plan-recovery banner. Rendered whenever the
              viewer has a payment_problem/suspended plan for this
              pathway, ABOVE the CTA card. Also drives suppression
              of the standard "Unlock" CTA below (Rule D reality —
              the member can't buy a duplicate plan). */}
          {pathway.member_plan_state && (
            <PlanRecoveryBanner
              state={pathway.member_plan_state}
              timezone={space?.timezone ?? null}
            />
          )}

          {/* CTA card — suppressed for suspended plans; a
              payment_problem member still sees their normal
              "Continue" flow because access is live during grace. */}
          {pathway.member_plan_state?.status !== 'suspended' && (
          <div className="rounded-2xl border border-border bg-white p-6">
            <div className="mb-4 space-y-2">
              {/* Access badge */}
              {locked ? (
                <>
                  {priceLabel && (
                    <p className="font-serif text-2xl font-bold text-navy-900">{priceLabel}</p>
                  )}
                  <p className="text-[13px] text-black">
                    {isPaymentOptionsMode
                      ? (publishedOptions.length > 1
                          ? `${publishedOptions.length} pass options — pay in full`
                          : 'Select a pass at checkout')
                      : pathway.access_type === 'subscription' ? 'Monthly access required' : 'Pay in full'}
                  </p>
                </>
              ) : isComingSoon ? (
                <p className="text-[14px] font-semibold text-black">Coming soon</p>
              ) : locked && isPaymentOptionsMode && publishedOptions.length === 0 ? (
                <p className="text-[14px] text-black">Opening soon — options coming</p>
              ) : pathway.step_count > 0 ? (
                <>
                  <div className="mb-1 flex items-baseline justify-between text-xs text-black">
                    <span>{pathway.completed_count} of {pathway.step_count} complete</span>
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
                </>
              ) : null}
            </div>

            {/* Step count */}
            {pathway.step_count > 0 && (
              <p className="mb-4 text-[13px] text-black">
                {pathway.step_count} step{pathway.step_count !== 1 ? 's' : ''}
              </p>
            )}

            {/* CTA button */}
            {isComingSoon ? (
              <div
                className="flex w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-[14px] font-medium"
                style={{
                  background: 'var(--fc-accent-soft, rgba(56,160,158,0.08))',
                  color: 'var(--fc-accent, #0f766e)',
                }}
              >
                <svg
                  className="h-3.5 w-3.5"
                  style={{ color: 'var(--fc-accent, #0d9488)' }}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Coming soon
              </div>
            ) : locked ? (
              <>
                <Link
                  href={`/spaces/${slug}/pathways/${pathwaySlug}/checkout`}
                  className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                  style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
                >
                  {unlockLabel ?? 'Unlock'}
                </Link>
                <p className="mt-2 text-center text-[11px] text-black">Secure checkout via Stripe</p>
              </>
            ) : pathway.steps.length > 0 && continueHref ? (
              <Link
                href={continueHref}
                className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
              >
                {pathway.completed_count === 0 ? 'Begin pathway' : pathway.completed_count >= pathway.step_count ? 'Review' : 'Continue'}
              </Link>
            ) : (
              <Link
                href={`/spaces/${slug}/pathways/${pathwaySlug}`}
                className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
              >
                View pathway
              </Link>
            )}

            {/* Link to full pathway overview */}
            <Link
              href={`/spaces/${slug}/pathways/${pathwaySlug}`}
              className="mt-3 block text-center text-[12px] text-black transition-colors hover:text-[color:var(--fc-accent,#0d9488)]"
            >
              View all steps →
            </Link>
          </div>
          )}

          {/* Access type label */}
          {!locked && !isComingSoon && (
            <div className="rounded-xl border border-border bg-white px-4 py-3 text-center">
              <span
                className="rounded-full px-3 py-1 text-[11px] font-semibold"
                style={
                  pathway.access_type === 'free'
                    ? { background: 'rgba(16,185,129,0.10)', color: '#065F46' }
                    : {
                        background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
                        color: 'var(--fc-accent, #0f766e)',
                      }
                }
              >
                {pathway.access_type === 'free'
                  ? 'Free'
                  : pathway.access_type === 'included'
                  ? 'Included'
                  : 'Access granted'}
              </span>
            </div>
          )}
        </div>
      </div>

    </div>
  )
}
