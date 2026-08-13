import { notFound } from 'next/navigation'
import Link from 'next/link'
import type { Metadata } from 'next'
import { getPublicOfferPage, getSpace, getMe } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import { formatPathwayPrice } from '@/lib/pathwayAccess'
import RichTextRenderer from '@/components/RichTextRenderer'
import type {
  OfferCreatorSection,
  OfferFaqsSection,
  OfferInvitationSection,
  OfferPageStatus,
  OfferPracticalSection,
  OfferSectionsConfig,
  OfferWhatsIncludedSection,
  PublicOfferPage,
} from '@/types/platform'

/**
 * Public Offer Page.
 *
 * A structured, calm invitation into a Creator's Pathway. Sections
 * render in a fixed order (Hero → Invitation → What's included →
 * Practical → About the creator → FAQs → Final CTA); each section
 * only appears if the creator enabled it AND it has actual content,
 * so a barely-filled Offer Page still looks composed rather than
 * skeletal.
 *
 * The collective palette from ``/spaces/[slug]/layout.tsx`` already
 * scopes ``--fc-accent`` / ``--fc-accent-soft`` / ``--fc-accent-line``
 * around this route via ``CollectiveThemeProvider`` — this page reads
 * those vars for the hero band and CTA without depending on any local
 * theme prop.
 *
 * Access states drive CTA copy:
 *   - viewer already has access → "Continue"
 *   - locked pathway            → "Join this Pathway" (with price shown)
 *   - free / included pathway   → "Begin this Pathway"
 *   - signed-out                → "Sign in to continue" (form handles the rest)
 *
 * The ``?ref=offer:{id}`` query hint is appended to every CTA that
 * routes into the target so downstream analytics / conversion tracking
 * can attribute the click without changing checkout behaviour today.
 */

interface Props {
  params: Promise<{ slug: string; offerSlug: string }>
}

// ---------------------------------------------------------------------------
// Metadata — title, description, Open Graph. Static — no runtime data
// leaks here so link previews stay fast.
// ---------------------------------------------------------------------------

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug, offerSlug } = await params
  const offer: PublicOfferPage | null = await getPublicOfferPage(slug, offerSlug)
  if (!offer) return { title: 'Offer' }

  const description =
    offer.promise
    || (typeof offer.target?.description === 'string' ? offer.target.description : null)
    || null

  const ogImage = offer.hero_image_url
    ? resolveMediaUrl(offer.hero_image_url) ?? undefined
    : undefined

  return {
    title: offer.title,
    description: description ?? undefined,
    openGraph: {
      title: offer.title,
      description: description ?? undefined,
      images: ogImage ? [{ url: ogImage }] : undefined,
      type: 'website',
    },
    twitter: {
      card: ogImage ? 'summary_large_image' : 'summary',
      title: offer.title,
      description: description ?? undefined,
      images: ogImage ? [ogImage] : undefined,
    },
  }
}

// ---------------------------------------------------------------------------
// Section shape normalisers — the raw ``sections_config`` dict is
// intentionally loose on the backend so future shape changes don't
// break existing rows. We narrow at the render boundary.
// ---------------------------------------------------------------------------

function readInvitation(raw: unknown): OfferInvitationSection {
  const s = (raw ?? {}) as Partial<OfferInvitationSection>
  return {
    enabled: !!s.enabled,
    body: typeof s.body === 'string' ? s.body : null,
  }
}
function readWhatsIncluded(raw: unknown): OfferWhatsIncludedSection {
  const s = (raw ?? {}) as Partial<OfferWhatsIncludedSection>
  return {
    enabled: !!s.enabled,
    items: Array.isArray(s.items) ? s.items.filter((v): v is string => typeof v === 'string' && v.trim() !== '') : [],
  }
}
function readPractical(raw: unknown): OfferPracticalSection {
  const s = (raw ?? {}) as Partial<OfferPracticalSection>
  return {
    enabled: !!s.enabled,
    dates: (s.dates as string | null | undefined) ?? null,
    duration: (s.duration as string | null | undefined) ?? null,
    location: (s.location as string | null | undefined) ?? null,
    format: (s.format as string | null | undefined) ?? null,
    access_period: (s.access_period as string | null | undefined) ?? null,
    capacity: (s.capacity as string | null | undefined) ?? null,
    requirements: (s.requirements as string | null | undefined) ?? null,
  }
}
function readFaqs(raw: unknown): OfferFaqsSection {
  const s = (raw ?? {}) as Partial<OfferFaqsSection>
  const items = Array.isArray(s.items) ? s.items : []
  return {
    enabled: !!s.enabled,
    items: items
      .map((it) => ({
        question: typeof it?.question === 'string' ? it.question.trim() : '',
        answer:   typeof it?.answer   === 'string' ? it.answer.trim()   : '',
      }))
      .filter((it) => it.question && it.answer),
  }
}
function readCreator(raw: unknown): OfferCreatorSection {
  const s = (raw ?? {}) as Partial<OfferCreatorSection>
  return { enabled: !!s.enabled }
}

function normalise(raw: PublicOfferPage['sections_config']): OfferSectionsConfig {
  const src = raw ?? {}
  return {
    invitation:     readInvitation((src as Record<string, unknown>).invitation),
    whats_included: readWhatsIncluded((src as Record<string, unknown>).whats_included),
    practical:      readPractical((src as Record<string, unknown>).practical),
    faqs:           readFaqs((src as Record<string, unknown>).faqs),
    creator:        readCreator((src as Record<string, unknown>).creator),
  }
}

// A rich-text body is "empty" when TipTap gave us a doc with no text
// content — we detect this so a section that was enabled but never
// filled in doesn't render a naked heading over blank space.
function hasRichTextContent(body: string | null): boolean {
  if (!body) return false
  const trimmed = body.trim()
  if (!trimmed) return false
  try {
    const parsed = JSON.parse(trimmed) as { content?: unknown[] }
    const stack: unknown[] = Array.isArray(parsed?.content) ? [...parsed.content] : []
    while (stack.length) {
      const node = stack.shift() as Record<string, unknown> | undefined
      if (!node) continue
      if (typeof node.text === 'string' && node.text.trim()) return true
      if (Array.isArray(node.content)) stack.push(...node.content)
    }
    return false
  } catch {
    return trimmed.length > 0
  }
}

function hasPracticalContent(p: OfferPracticalSection): boolean {
  return [p.dates, p.duration, p.location, p.format, p.access_period, p.capacity, p.requirements]
    .some((v) => typeof v === 'string' && v.trim() !== '')
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function PublicOfferPageRoute({ params }: Props) {
  const { slug, offerSlug } = await params

  const [offer, space, me]: [
    PublicOfferPage | null,
    Awaited<ReturnType<typeof getSpace>>,
    Awaited<ReturnType<typeof getMe>>,
  ] = await Promise.all([
    getPublicOfferPage(slug, offerSlug),
    getSpace(slug),
    getMe(),
  ])

  if (!offer) notFound()

  const sections = normalise(offer.sections_config)
  const target = offer.target
  const isAuthed = !!me
  const hasAccess = offer.user_has_target_access
  const status: OfferPageStatus = offer.status

  // ── CTA routing + copy ──────────────────────────────────────────────
  //
  // We prefer the backend-provided ``checkout_path`` / ``enter_path``
  // so the frontend never hard-codes target-specific URL shapes.
  // ``?ref=offer:{id}`` is appended so downstream analytics can
  // attribute this click without changing checkout behaviour.
  const refHint = `ref=offer%3A${encodeURIComponent(offer.id)}`
  function withRef(path: string | null | undefined): string {
    if (!path) return '#'
    const sep = path.includes('?') ? '&' : '?'
    return `${path}${sep}${refHint}`
  }

  // Free / included pathways never enter the checkout flow — the
  // enter_path is the correct destination whether or not the viewer
  // has a session, so we don't gate on isAuthed for those cases.
  const targetIsFree = target.access_type === 'free' || target.access_type === 'included'
  const priceLabel = formatPathwayPrice(target.price_cents, target.currency, target.billing_interval)
  const showPrice = !targetIsFree && !!priceLabel

  let ctaHref: string
  let ctaLabel: string
  let ctaSubLabel: string | null = null

  if (!isAuthed && !targetIsFree) {
    // Sign-in gate for paid targets. Preserve the intended destination
    // so the login flow can bounce them into checkout on success.
    const next = encodeURIComponent(withRef(target.checkout_path))
    ctaHref = `/login?next=${next}`
    ctaLabel = 'Sign in to continue'
    ctaSubLabel = 'You\u2019ll come right back here'
  } else if (hasAccess) {
    ctaHref = withRef(target.enter_path)
    ctaLabel = 'Continue'
    ctaSubLabel = `You already have access to ${target.title}`
  } else if (targetIsFree) {
    ctaHref = withRef(target.enter_path ?? target.checkout_path)
    ctaLabel = 'Begin this Pathway'
  } else {
    ctaHref = withRef(target.checkout_path)
    ctaLabel = 'Join this Pathway'
    ctaSubLabel = 'Secure checkout'
  }

  // ── Hero image resolution ──────────────────────────────────────────
  //
  // Order: Offer Page hero → Pathway cover → Collective cover art.
  // Location artwork is intentionally excluded because it's a shared
  // atlas image, not the creator's own — falling all the way to it
  // would feel generic when the collective has its own cover.
  const heroImageSrc =
    resolveMediaUrl(offer.hero_image_url)
    ?? resolveMediaUrl(target.cover_image_url)
    ?? resolveMediaUrl(space?.cover_image_url ?? null)
    ?? null

  return (
    <div className="mx-auto max-w-4xl px-4 pb-16 pt-6 md:px-6 md:pt-8">

      {/* Draft banner for owner preview — public visitors only ever
          hit this route for published pages (backend enforces 404
          otherwise), so this is safe. */}
      {status !== 'published' && (
        <div
          className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-2.5 text-[12.5px]"
          style={{
            background: 'rgba(214,177,63,0.08)',
            borderColor: 'rgba(214,177,63,0.35)',
            color: '#8a6a1f',
          }}
        >
          <span className="font-semibold uppercase tracking-wider">
            {status === 'draft' ? 'Draft preview' : 'Archived preview'}
          </span>
          <span>Visible to you as an owner. Not published to the public.</span>
        </div>
      )}

      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <Hero
        title={offer.title}
        promise={offer.promise}
        heroImageSrc={heroImageSrc}
        priceLabel={showPrice ? priceLabel : null}
        ctaHref={ctaHref}
        ctaLabel={ctaLabel}
        ctaSubLabel={ctaSubLabel}
      />

      {/* ── Invitation ───────────────────────────────────────────────── */}
      {sections.invitation.enabled && hasRichTextContent(sections.invitation.body) && (
        <SectionBlock title="Invitation">
          <div className="offer-invitation">
            <RichTextRenderer content={sections.invitation.body ?? ''} />
          </div>
        </SectionBlock>
      )}

      {/* ── What's included ──────────────────────────────────────────── */}
      {sections.whats_included.enabled && sections.whats_included.items.length > 0 && (
        <SectionBlock title="What's included">
          <WhatsIncludedList items={sections.whats_included.items} />
        </SectionBlock>
      )}

      {/* ── Practical details ────────────────────────────────────────── */}
      {sections.practical.enabled && hasPracticalContent(sections.practical) && (
        <SectionBlock title="Practical details">
          <PracticalGrid value={sections.practical} />
        </SectionBlock>
      )}

      {/* ── About the creator ────────────────────────────────────────── */}
      {sections.creator.enabled && space && (
        <SectionBlock title="About the creator">
          <CreatorCard
            spaceName={space.name}
            tagline={space.tagline}
            description={space.description}
            logoUrl={space.logo_url ?? null}
            creatorName={typeof (space as { creator_name?: string | null }).creator_name === 'string'
              ? (space as { creator_name?: string | null }).creator_name ?? null
              : null}
          />
        </SectionBlock>
      )}

      {/* ── FAQs ─────────────────────────────────────────────────────── */}
      {sections.faqs.enabled && sections.faqs.items.length > 0 && (
        <SectionBlock title="Common questions">
          <FaqList items={sections.faqs.items} />
        </SectionBlock>
      )}

      {/* ── Closing CTA ───────────────────────────────────────────────
          A single calm invitation after reading. Deliberately smaller
          than the hero so it reads as "when you're ready" rather than
          a second sales banner. */}
      <ClosingCta
        ctaHref={ctaHref}
        ctaLabel={ctaLabel}
        ctaSubLabel={ctaSubLabel}
        priceLabel={showPrice ? priceLabel : null}
      />

      {/* Small scoped tweaks so the Invitation TipTap output reads as
          calm body copy in this page context rather than the denser
          shared style used in editor/manager surfaces. */}
      <style>{`
        .offer-invitation .rich-text-content { font-size: 15.5px; line-height: 1.85; color: #0C1826; }
        .offer-invitation .rich-text-content p { margin: 0 0 1.1em; }
        .offer-invitation .rich-text-content h1,
        .offer-invitation .rich-text-content h2,
        .offer-invitation .rich-text-content h3 {
          font-family: 'Playfair Display', Georgia, serif;
          font-weight: 500;
          font-size: 20px;
          line-height: 1.35;
          color: #0C1826;
          margin: 1.8em 0 0.6em;
        }
        .offer-invitation .rich-text-content a {
          color: var(--fc-accent, #38A09E);
          text-decoration: underline;
          text-decoration-thickness: 1px;
          text-underline-offset: 3px;
        }
        .offer-invitation .rich-text-content ul,
        .offer-invitation .rich-text-content ol { margin: 0 0 1.1em 1.2em; }
        .offer-invitation .rich-text-content li { margin: 0.35em 0; }
      `}</style>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Hero
// ---------------------------------------------------------------------------

function Hero({
  title, promise, heroImageSrc, priceLabel,
  ctaHref, ctaLabel, ctaSubLabel,
}: {
  title: string
  promise: string | null
  heroImageSrc: string | null
  priceLabel: string | null
  ctaHref: string
  ctaLabel: string
  ctaSubLabel: string | null
}) {
  return (
    <section
      className="relative mb-8 overflow-hidden rounded-2xl md:mb-10"
      style={{
        background: heroImageSrc
          ? '#0C1826'
          : 'linear-gradient(135deg, var(--fc-accent-soft, rgba(56,160,158,0.10)) 0%, rgba(255,255,255,0.55) 100%)',
      }}
    >
      {heroImageSrc && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={heroImageSrc}
            alt=""
            aria-hidden="true"
            className="absolute inset-0 h-full w-full object-cover"
          />
          <div
            className="absolute inset-0"
            style={{ background: 'linear-gradient(135deg, rgba(7,24,36,0.72) 0%, rgba(7,56,58,0.55) 100%)' }}
          />
        </>
      )}
      <div className="relative px-6 py-10 md:px-10 md:py-14">
        <div
          className="mb-4 h-[2px] w-8 rounded-full"
          style={{ background: 'var(--fc-accent, #38A09E)' }}
        />
        <h1
          className="font-serif text-[28px] leading-[1.15] md:text-[38px] md:leading-[1.1]"
          style={{ color: heroImageSrc ? '#FFFFFF' : '#0C1826' }}
        >
          {title}
        </h1>
        {promise && (
          <p
            className="mt-3 max-w-2xl text-[15.5px] leading-relaxed md:text-[17px]"
            style={{ color: heroImageSrc ? 'rgba(255,255,255,0.92)' : 'rgba(12,24,38,0.78)' }}
          >
            {promise}
          </p>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-4 md:mt-8">
          <Link
            href={ctaHref}
            className="inline-flex items-center justify-center rounded-full px-6 py-3 text-[14.5px] font-semibold text-white shadow-sm transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
          >
            {ctaLabel}
          </Link>
          {priceLabel && (
            <div className="flex flex-col">
              <span
                className="text-[16px] font-semibold"
                style={{ color: heroImageSrc ? '#FFFFFF' : '#0C1826' }}
              >
                {priceLabel}
              </span>
              {ctaSubLabel && (
                <span
                  className="text-[12px]"
                  style={{ color: heroImageSrc ? 'rgba(255,255,255,0.75)' : 'rgba(12,24,38,0.55)' }}
                >
                  {ctaSubLabel}
                </span>
              )}
            </div>
          )}
          {!priceLabel && ctaSubLabel && (
            <span
              className="text-[12.5px]"
              style={{ color: heroImageSrc ? 'rgba(255,255,255,0.80)' : 'rgba(12,24,38,0.60)' }}
            >
              {ctaSubLabel}
            </span>
          )}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section shell — consistent spacing + heading rhythm across every
// enabled section.
// ---------------------------------------------------------------------------

function SectionBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10 md:mb-12">
      <h2
        className="mb-4 font-serif text-[20px] md:text-[22px]"
        style={{ color: '#0C1826' }}
      >
        {title}
      </h2>
      <div>{children}</div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// What's included — checkmark rows on a soft accent background so
// they read as a considered list, not a browser bullet list.
// ---------------------------------------------------------------------------

function WhatsIncludedList({ items }: { items: string[] }) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {items.map((item, i) => (
        <li
          key={i}
          className="flex items-start gap-3 rounded-xl border px-4 py-3"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.06))',
            borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.18))',
          }}
        >
          <span
            aria-hidden="true"
            className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
            style={{ background: 'var(--fc-accent, #38A09E)' }}
          >
            ✓
          </span>
          <span className="text-[14.5px] leading-snug text-[#0C1826]">{item}</span>
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Practical grid — auto-fitting rows so two or seven fields both
// look intentional. Field labels are muted; values are the emphasis.
// ---------------------------------------------------------------------------

function PracticalGrid({ value }: { value: OfferPracticalSection }) {
  const rows: Array<{ label: string; value: string }> = []
  const push = (label: string, v: string | null) => {
    if (v && v.trim()) rows.push({ label, value: v.trim() })
  }
  push('Dates', value.dates)
  push('Duration', value.duration)
  push('Location', value.location)
  push('Format', value.format)
  push('Access', value.access_period)
  push('Capacity', value.capacity)

  return (
    <div>
      <dl
        className="grid gap-x-8 gap-y-4 rounded-xl border bg-white px-5 py-5 sm:grid-cols-2 md:px-7 md:py-6"
        style={{ borderColor: 'rgba(12,24,38,0.08)' }}
      >
        {rows.map(({ label, value: v }) => (
          <div key={label} className="min-w-0">
            <dt
              className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
              style={{ color: 'rgba(12,24,38,0.50)' }}
            >
              {label}
            </dt>
            <dd className="text-[15px] font-medium leading-snug text-[#0C1826]">
              {v}
            </dd>
          </div>
        ))}
      </dl>
      {value.requirements && value.requirements.trim() && (
        <div
          className="mt-4 rounded-xl border px-5 py-4"
          style={{
            borderColor: 'rgba(12,24,38,0.08)',
            background: 'rgba(12,24,38,0.02)',
          }}
        >
          <p
            className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
            style={{ color: 'rgba(12,24,38,0.50)' }}
          >
            You&rsquo;ll need
          </p>
          <p className="text-[14.5px] leading-relaxed text-[#0C1826] whitespace-pre-line">
            {value.requirements}
          </p>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// About the creator — warm intro drawn from the Collective's own
// profile. Deliberately doesn't require a bio/avatar field on the
// user — the collective's name, tagline, description, and logo carry
// the tone.
// ---------------------------------------------------------------------------

function CreatorCard({
  spaceName, tagline, description, logoUrl, creatorName,
}: {
  spaceName: string
  tagline: string | null
  description: string | null
  logoUrl: string | null
  creatorName: string | null
}) {
  const resolvedLogo = resolveMediaUrl(logoUrl)
  return (
    <div
      className="flex flex-col gap-5 rounded-xl border bg-white p-5 md:flex-row md:items-start md:p-6"
      style={{ borderColor: 'rgba(12,24,38,0.08)' }}
    >
      <div
        className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl md:h-20 md:w-20"
        style={{
          background: resolvedLogo ? '#FFFFFF' : 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
          border: resolvedLogo ? '1px solid rgba(12,24,38,0.06)' : 'none',
        }}
      >
        {resolvedLogo ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img src={resolvedLogo} alt="" className="h-full w-full object-contain" />
        ) : (
          <span
            aria-hidden="true"
            className="font-serif text-[22px]"
            style={{ color: 'var(--fc-accent, #38A09E)' }}
          >
            {spaceName.slice(0, 1)}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-serif text-[18px] leading-tight text-[#0C1826] md:text-[19px]">
          {spaceName}
        </p>
        {tagline && (
          <p
            className="mt-0.5 text-[13.5px] italic"
            style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}
          >
            {tagline}
          </p>
        )}
        {description && (
          <p className="mt-3 text-[14.5px] leading-relaxed text-[#0C1826]">
            {description}
          </p>
        )}
        {creatorName && (
          <p
            className="mt-3 text-[12px]"
            style={{ color: 'rgba(12,24,38,0.55)' }}
          >
            Hosted by {creatorName}
          </p>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FAQ list — native <details> for zero-JS accordion behaviour, styled
// so it reads as part of the page rather than a browser default.
// ---------------------------------------------------------------------------

function FaqList({ items }: { items: { question: string; answer: string }[] }) {
  return (
    <div
      className="divide-y overflow-hidden rounded-xl border bg-white"
      style={{
        borderColor: 'rgba(12,24,38,0.08)',
      }}
    >
      {items.map((item, i) => (
        <details key={i} className="group offer-faq">
          <summary
            className="flex cursor-pointer list-none items-start justify-between gap-4 px-5 py-4 text-[15px] font-medium text-[#0C1826] transition-colors hover:bg-slate-50 md:px-6"
          >
            <span className="min-w-0 flex-1 leading-snug">{item.question}</span>
            <span
              aria-hidden="true"
              className="mt-1 text-[14px] transition-transform group-open:rotate-180"
              style={{ color: 'var(--fc-accent, #38A09E)' }}
            >
              ▾
            </span>
          </summary>
          <div className="px-5 pb-5 pt-1 text-[14.5px] leading-relaxed text-[#0C1826] whitespace-pre-line md:px-6">
            {item.answer}
          </div>
        </details>
      ))}
      <style>{`
        .offer-faq > summary::-webkit-details-marker { display: none; }
      `}</style>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Closing CTA — one final calm invitation.
// ---------------------------------------------------------------------------

function ClosingCta({
  ctaHref, ctaLabel, ctaSubLabel, priceLabel,
}: {
  ctaHref: string
  ctaLabel: string
  ctaSubLabel: string | null
  priceLabel: string | null
}) {
  return (
    <section
      className="rounded-2xl border px-6 py-8 text-center md:px-10 md:py-10"
      style={{
        background: 'var(--fc-accent-soft, rgba(56,160,158,0.06))',
        borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.18))',
      }}
    >
      <p
        className="mx-auto max-w-md font-serif text-[19px] leading-snug md:text-[21px]"
        style={{ color: '#0C1826' }}
      >
        When you&rsquo;re ready.
      </p>
      <div className="mt-5 flex flex-wrap items-center justify-center gap-4">
        <Link
          href={ctaHref}
          className="inline-flex items-center justify-center rounded-full px-6 py-3 text-[14.5px] font-semibold text-white shadow-sm transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
        >
          {ctaLabel}
        </Link>
        {priceLabel && (
          <span className="text-[14.5px] font-semibold text-[#0C1826]">
            {priceLabel}
          </span>
        )}
      </div>
      {ctaSubLabel && (
        <p
          className="mt-2 text-[12px]"
          style={{ color: 'rgba(12,24,38,0.55)' }}
        >
          {ctaSubLabel}
        </p>
      )}
    </section>
  )
}
