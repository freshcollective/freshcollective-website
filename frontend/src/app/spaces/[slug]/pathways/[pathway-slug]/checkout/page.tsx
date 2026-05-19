import { notFound, redirect } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview, getSpace } from '@/lib/serverApi'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
import { isPathwayLocked, formatPathwayPrice } from '@/lib/pathwayAccess'
import type { PathwayWithSteps } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
}

export async function generateMetadata({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params
  const pathway = await getPathwayOverview(slug, pathwaySlug)
  return { title: pathway ? `Unlock ${pathway.title}` : 'Checkout' }
}

export default async function PathwayCheckoutPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params

  const [pathway, space]: [PathwayWithSteps | null, { name: string; slug: string } | null] =
    await Promise.all([
      getPathwayOverview(slug, pathwaySlug),
      getSpace(slug),
    ])

  if (!pathway || !space) notFound()

  const isComingSoon = pathway.status === 'coming_soon'
  const locked = !isComingSoon && isPathwayLocked(pathway.access_type)

  // Free or included pathways don't need checkout — redirect to overview
  if (!locked && !isComingSoon) {
    redirect(`/spaces/${slug}/pathways/${pathwaySlug}`)
  }

  const cs = getPathwayCoverStyle(pathwaySlug)
  const coverImageUrl = resolveMediaUrl(pathway.cover_image_url)
  const priceLabel = locked
    ? formatPathwayPrice(pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null

  const isSubscription = pathway.access_type === 'subscription'
  const overviewHref = `/spaces/${slug}/pathways/${pathwaySlug}`
  const aboutHref = `/spaces/${slug}/pathways/${pathwaySlug}/about`

  // Already has access
  if (pathway.user_has_access && locked) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12 md:px-6">
        <Link href={aboutHref} className="mb-6 block text-sm text-slate-400 hover:text-teal-600">
          ← Back to pathway
        </Link>
        <div
          className="rounded-2xl border bg-white p-8 text-center"
          style={{ borderColor: 'rgba(56,160,158,0.25)' }}
        >
          <div
            className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: 'rgba(56,160,158,0.10)' }}
          >
            <svg className="h-7 w-7 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h1 className="font-serif text-2xl text-navy-900">You already have access</h1>
          <p className="mt-2 text-[14px] text-slate-500">
            You already have access to <span className="font-semibold text-navy-900">{pathway.title}</span>.
          </p>
          <Link
            href={overviewHref}
            className="mt-6 inline-block rounded-full px-7 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {pathway.completed_count === 0 ? 'Begin pathway' : pathway.completed_count >= pathway.step_count ? 'Review' : 'Continue'}
          </Link>
        </div>
      </div>
    )
  }

  // Coming soon
  if (isComingSoon) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12 md:px-6">
        <Link href={aboutHref} className="mb-6 block text-sm text-slate-400 hover:text-teal-600">
          ← Back to pathway
        </Link>
        <div
          className="rounded-2xl border bg-white p-8 text-center"
          style={{ borderColor: '#E2E8F0' }}
        >
          <p className="font-serif text-2xl text-navy-900">{pathway.title}</p>
          <p className="mt-4 text-[14px] text-slate-500">This pathway is coming soon.</p>
        </div>
      </div>
    )
  }

  // Checkout shell (locked, no access)
  return (
    <div className="mx-auto max-w-2xl px-4 py-10 md:px-6">

      {/* Back link */}
      <Link href={aboutHref} className="mb-6 block text-sm text-slate-400 hover:text-teal-600">
        ← Back to pathway
      </Link>

      <h1 className="mb-1 font-serif text-2xl text-navy-900 md:text-3xl">
        Unlock {pathway.title}
      </h1>
      <p className="mb-8 text-[14px] text-slate-500">{space.name}</p>

      <div className="grid gap-6 md:grid-cols-[1fr_300px]">

        {/* Left: pathway summary */}
        <div className="space-y-5">

          {/* Cover / hero */}
          <div
            className="overflow-hidden rounded-2xl"
            style={{ background: cs.background, backgroundSize: cs.backgroundSize ?? 'auto' }}
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
                  style={{ background: 'linear-gradient(135deg, rgba(7,24,36,0.65) 0%, rgba(7,56,58,0.50) 100%)' }}
                />
              </>
            )}
            <div className="relative px-6 py-8">
              <p
                className="mb-1 text-[9px] font-bold uppercase tracking-[0.20em]"
                style={{ color: coverImageUrl ? 'rgba(255,255,255,0.65)' : cs.labelColor }}
              >
                Pathway · {space.name}
              </p>
              <h2
                className="font-serif text-xl md:text-2xl"
                style={{ color: coverImageUrl ? '#FFFFFF' : cs.titleColor }}
              >
                {pathway.title}
              </h2>
              {pathway.description && (
                <p
                  className="mt-2 max-w-md text-[13px] leading-relaxed"
                  style={{ color: (coverImageUrl || cs.isDark) ? 'rgba(255,255,255,0.70)' : '#64748B' }}
                >
                  {pathway.description}
                </p>
              )}
            </div>
          </div>

          {/* Access type */}
          <div className="rounded-xl border border-border bg-white p-4">
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Access type
            </p>
            <p className="text-[14px] font-medium text-navy-900">
              {isSubscription ? 'Monthly subscription' : 'One-off purchase'}
            </p>
            <p className="mt-0.5 text-[13px] text-slate-500">
              {isSubscription
                ? 'Pay monthly to maintain access.'
                : 'Unlock permanently with a single payment.'}
            </p>
          </div>

          {/* What you get */}
          <div className="rounded-xl border border-border bg-white p-4">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              What&apos;s included
            </p>
            <ul className="space-y-2">
              {[
                `Access to all ${pathway.step_count > 0 ? pathway.step_count : ''} pathway steps`,
                'Progress tracking',
                'Resources attached to steps',
              ].map((item) => (
                <li key={item} className="flex items-start gap-2 text-[13px] text-slate-600">
                  <span className="mt-0.5 shrink-0 text-[#38A09E]">✓</span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Right: payment summary card */}
        <div className="flex flex-col gap-4">
          <div
            className="rounded-2xl bg-white p-6"
            style={{ border: '1px solid #E2E8F0' }}
          >
            <p className="mb-4 text-[13px] font-semibold text-slate-400 uppercase tracking-wide">
              Payment summary
            </p>

            <div className="space-y-3 text-[14px]">
              <div className="flex items-center justify-between">
                <span className="text-slate-600">
                  {isSubscription ? 'Monthly subscription' : 'One-off purchase'}
                </span>
                <span className="font-semibold text-navy-900">
                  {priceLabel ?? '—'}
                </span>
              </div>
              <div className="flex items-start justify-between gap-2">
                <span className="text-[12px] text-slate-400">
                  Payment processing fees apply at checkout (Stripe)
                </span>
              </div>
              <div
                className="flex items-center justify-between border-t pt-3 font-semibold"
                style={{ borderColor: '#E2E8F0' }}
              >
                <span className="text-navy-900">Total</span>
                <span className="text-navy-900">{priceLabel ?? '—'}</span>
              </div>
            </div>

            {/* Disabled checkout button */}
            <button
              disabled
              type="button"
              className="mt-5 w-full cursor-not-allowed rounded-full px-5 py-3 text-[14px] font-semibold opacity-60"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)', color: '#fff' }}
            >
              Checkout coming soon
            </button>

            <p className="mt-3 text-center text-[11px] leading-relaxed text-slate-400">
              Payments are not connected yet. This page is ready for Stripe integration later.
            </p>

            {/*
              TODO: Stripe Checkout integration
              1. On button click → POST /api/checkout/pathway/{pathway_id}/session
                 → Create pending PaymentTransaction row
                 → Create Stripe Checkout Session with price_id
                 → Return session URL
              2. Redirect member to Stripe Checkout
              3. On Stripe webhook (checkout.session.completed):
                 → Mark PaymentTransaction as succeeded
                 → Create PathwayEntitlement (source=one_time_purchase or subscription)
                 → Send access-granted email
            */}
          </div>

          <Link
            href={aboutHref}
            className="block text-center text-[12px] text-slate-400 hover:text-teal-600 transition-colors"
          >
            ← View pathway details
          </Link>
        </div>
      </div>
    </div>
  )
}
