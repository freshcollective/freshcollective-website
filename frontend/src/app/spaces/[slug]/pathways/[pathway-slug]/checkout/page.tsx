import { notFound, redirect } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview, getSpace, getMe } from '@/lib/serverApi'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
import { isPathwayLocked, formatPathwayPrice } from '@/lib/pathwayAccess'
import { CheckoutButton } from '@/components/checkout/CheckoutButton'
import { PaymentOptionSelector } from '@/components/checkout/PaymentOptionSelector'
import type { PathwayWithSteps } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
  searchParams: Promise<{
    success?: string
    cancelled?: string
    session_id?: string
    payment_option_id?: string
    payment_option_schedule_id?: string
  }>
}

export async function generateMetadata({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params
  const pathway = await getPathwayOverview(slug, pathwaySlug)
  return { title: pathway ? `Unlock ${pathway.title}` : 'Checkout' }
}

export default async function PathwayCheckoutPage({ params, searchParams }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params
  const { success, cancelled, payment_option_id, payment_option_schedule_id } = await searchParams

  const [pathway, space, me] = await Promise.all([
    getPathwayOverview(slug, pathwaySlug),
    getSpace(slug),
    getMe(),
  ])
  const isAuthenticated = me !== null

  if (!pathway || !space) notFound()

  const isComingSoon = pathway.status === 'coming_soon'
  const locked = !isComingSoon && isPathwayLocked(pathway.access_type)

  // Free or included pathways don't need checkout
  if (!locked && !isComingSoon) {
    redirect(`/spaces/${slug}/pathways/${pathwaySlug}`)
  }

  const isSubscription = pathway.access_type === 'subscription'
  const isPaymentOptionsMode = pathway.pricing_mode === 'payment_options'
  const overviewHref = `/spaces/${slug}/pathways/${pathwaySlug}`
  const aboutHref = `/spaces/${slug}/pathways/${pathwaySlug}/about`
  const cs = getPathwayCoverStyle(pathwaySlug)
  const coverImageUrl = resolveMediaUrl(pathway.cover_image_url)
  const priceLabel = locked && !isPaymentOptionsMode
    ? formatPathwayPrice(pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null

  // ── Access already granted (after successful purchase or admin grant) ──
  if (pathway.user_has_access && locked) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12 md:px-6">
        <Link href={aboutHref} className="mb-6 block text-sm text-black hover:text-[color:var(--fc-accent,#0d9488)]">
          ← Back to pathway
        </Link>
        <div
          className="rounded-2xl border bg-white p-8 text-center"
          style={{ borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.25))' }}
        >
          <div
            className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))' }}
          >
            <svg
              className="h-7 w-7"
              style={{ color: 'var(--fc-accent, #0d9488)' }}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          {success ? (
            <>
              <h1 className="font-serif text-2xl text-navy-900">Payment successful</h1>
              <p className="mt-2 text-[14px] text-black">
                You now have access to <span className="font-semibold text-navy-900">{pathway.title}</span>.
              </p>
            </>
          ) : (
            <>
              <h1 className="font-serif text-2xl text-navy-900">You already have access</h1>
              <p className="mt-2 text-[14px] text-black">
                You already have access to <span className="font-semibold text-navy-900">{pathway.title}</span>.
              </p>
            </>
          )}
          <Link
            href={overviewHref}
            className="mt-6 inline-block rounded-full px-7 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
          >
            {pathway.completed_count === 0 ? 'Begin pathway' : pathway.completed_count >= pathway.step_count ? 'Review' : 'Continue'}
          </Link>
        </div>
      </div>
    )
  }

  // ── Payment received but webhook not yet processed ──
  // (success param is set but user_has_access is still false)
  if (success) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12 md:px-6">
        <div
          className="rounded-2xl border bg-white p-8 text-center"
          style={{ borderColor: '#E2E8F0' }}
        >
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-amber-50">
            <svg className="h-7 w-7 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h1 className="font-serif text-2xl text-navy-900">Payment received</h1>
          <p className="mt-2 text-[14px] text-black">
            We&apos;re finalising your access to <span className="font-semibold text-navy-900">{pathway.title}</span>. This usually takes a moment.
          </p>
          <Link
            href={`/spaces/${slug}/pathways/${pathwaySlug}/checkout?success=true`}
            className="mt-6 inline-block rounded-full border px-7 py-2.5 text-[14px] font-semibold transition-colors"
            style={{
              borderColor: 'var(--fc-accent-line, #99f6e4)',
              background: 'var(--fc-accent-soft, #f0fdfa)',
              color: 'var(--fc-accent, #0f766e)',
            }}
          >
            Refresh to check access
          </Link>
        </div>
      </div>
    )
  }

  // ── Coming soon ──
  if (isComingSoon) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12 md:px-6">
        <Link href={aboutHref} className="mb-6 block text-sm text-black hover:text-[color:var(--fc-accent,#0d9488)]">
          ← Back to pathway
        </Link>
        <div
          className="rounded-2xl border bg-white p-8 text-center"
          style={{ borderColor: '#E2E8F0' }}
        >
          <p className="font-serif text-2xl text-navy-900">{pathway.title}</p>
          <p className="mt-4 text-[14px] text-black">This pathway is coming soon.</p>
        </div>
      </div>
    )
  }

  // ── Checkout cancelled ──
  if (cancelled) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12 md:px-6">
        <Link href={aboutHref} className="mb-6 block text-sm text-black hover:text-[color:var(--fc-accent,#0d9488)]">
          ← Back to pathway
        </Link>
        <div
          className="rounded-2xl border bg-white p-8 text-center"
          style={{ borderColor: '#E2E8F0' }}
        >
          <h1 className="font-serif text-2xl text-navy-900">Checkout cancelled</h1>
          <p className="mt-2 text-[14px] text-black">
            No payment was taken. You can try again whenever you&apos;re ready.
          </p>
          <Link
            href={`/spaces/${slug}/pathways/${pathwaySlug}/checkout`}
            className="mt-6 inline-block rounded-full border border-slate-200 bg-white px-7 py-2.5 text-[14px] font-semibold text-black transition-colors hover:bg-slate-50"
          >
            Back to checkout
          </Link>
        </div>
      </div>
    )
  }

  // ── Subscription pathway — not yet wired (Phase 3) ──
  if (isSubscription) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12 md:px-6">
        <Link href={aboutHref} className="mb-6 block text-sm text-black hover:text-[color:var(--fc-accent,#0d9488)]">
          ← Back to pathway
        </Link>
        <div
          className="rounded-2xl border bg-white p-8 text-center"
          style={{ borderColor: '#E2E8F0' }}
        >
          <p className="font-serif text-2xl text-navy-900">{pathway.title}</p>
          <p className="mt-4 text-[14px] text-black">
            Subscription billing is coming soon. Check back shortly.
          </p>
        </div>
      </div>
    )
  }

  // ── Main checkout UI (locked one-time pathway, no access) ──
  return (
    <div className="mx-auto max-w-2xl px-4 py-10 md:px-6">

      {/* Back link */}
      <Link href={aboutHref} className="mb-6 block text-sm text-slate-400 hover:text-[color:var(--fc-accent,#0d9488)]">
        ← Back to pathway
      </Link>

      <h1 className="mb-1 font-serif text-2xl text-navy-900 md:text-3xl">
        Unlock {pathway.title}
      </h1>
      <p className="mb-8 text-[14px] text-black">{space.name}</p>

      <div className="grid gap-6 md:grid-cols-[1fr_300px]">

        {/* Left: pathway summary */}
        <div className="space-y-5">

          {/* Cover / hero */}
          <div
            className="relative overflow-hidden rounded-2xl"
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
                style={{ color: coverImageUrl ? '#FFFFFF' : cs.labelColor }}
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
                  style={{ color: (coverImageUrl || cs.isDark) ? '#FFFFFF' : '#000000' }}
                >
                  {pathway.description}
                </p>
              )}
            </div>
          </div>

          {/* Access type */}
          <div className="rounded-xl border border-border bg-white p-4">
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-black">
              Payment
            </p>
            {isPaymentOptionsMode ? (
              <>
                <p className="text-[14px] font-medium text-navy-900">Choose your term pass</p>
                <p className="mt-0.5 text-[13px] text-black">
                  Select the pass that suits your schedule. Pay in full to lock in your term.
                </p>
              </>
            ) : (
              <>
                <p className="text-[14px] font-medium text-navy-900">Pay in full</p>
                <p className="mt-0.5 text-[13px] text-black">
                  One payment to secure your term pass.
                </p>
              </>
            )}
          </div>

          {/* What you get */}
          <div className="rounded-xl border border-border bg-white p-4">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-black">
              What&apos;s included
            </p>
            <ul className="space-y-2">
              {(isPaymentOptionsMode ? [
                'In-person sessions across the 10-week term',
                'Monday evenings, Thursday evenings and Saturday mornings',
                'South Croydon, Victoria',
                'Full address shared after enrolment',
                'Session guidance and member information pathway',
              ] : [
                `Access to all ${pathway.step_count > 0 ? pathway.step_count : ''} pathway steps`,
                'Progress tracking',
                'Resources attached to steps',
              ]).map((item) => (
                <li key={item} className="flex items-start gap-2 text-[13px] text-black">
                  <span className="mt-0.5 shrink-0" style={{ color: 'var(--fc-accent, #38A09E)' }}>✓</span>
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
            <p className="mb-4 text-[13px] font-semibold text-black uppercase tracking-wide">
              {pathway.payment_options.length > 0 ? 'Choose your option' : 'Payment summary'}
            </p>

            {pathway.payment_options.length > 0 ? (
              <PaymentOptionSelector
                pathwayId={pathway.id}
                options={pathway.payment_options}
                isAuthenticated={isAuthenticated}
                initialOptionId={payment_option_id}
                initialScheduleId={payment_option_schedule_id ?? null}
              />
            ) : (
              <>
                <div className="space-y-3 text-[14px]">
                  <div className="flex items-center justify-between">
                    <span className="text-black">One-off purchase</span>
                    <span className="font-semibold text-navy-900">
                      {priceLabel ?? '—'}
                    </span>
                  </div>
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[12px] text-black">
                      Processed securely via Stripe
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
                <div className="mt-5">
                  <CheckoutButton
                    pathwayId={pathway.id}
                    label={priceLabel ? `Unlock for ${priceLabel}` : 'Unlock pathway'}
                    isAuthenticated={isAuthenticated}
                  />
                </div>
                {!isAuthenticated && (
                  <p className="mt-2 text-center text-[11px] leading-relaxed text-black">
                    Create a free account so we can save your access and connect your payment to your profile.
                  </p>
                )}
                {isAuthenticated && (
                  <p className="mt-3 text-center text-[11px] leading-relaxed text-black">
                    Secure checkout via Stripe. You&apos;ll be redirected to complete payment.
                  </p>
                )}
              </>
            )}
          </div>

          <Link
            href={aboutHref}
            className="block text-center text-[12px] text-black hover:text-[color:var(--fc-accent,#0d9488)] transition-colors"
          >
            ← View pathway details
          </Link>
        </div>
      </div>
    </div>
  )
}
