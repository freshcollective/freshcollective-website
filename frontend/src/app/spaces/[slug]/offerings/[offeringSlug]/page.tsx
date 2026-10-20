import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getMemberOffering } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import type { MemberOffering } from '@/types/platform'
import { AboutBlockRenderer } from '@/components/spaces/AboutBlockRenderer'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'

interface Props {
  params: Promise<{ slug: string; offeringSlug: string }>
}

function priceLabel(o: MemberOffering): string {
  if (o.pricing_kind === 'free') return 'Free'
  if (o.pricing_kind === 'one_time' && o.price_cents) {
    const d = o.price_cents / 100
    return `$${d % 1 === 0 ? d.toFixed(0) : d.toFixed(2)}`
  }
  return ''
}

/**
 * The member-facing Offering detail page — and the creator's Preview.
 *
 * One page, two audiences. A creator pressing Preview is redirected
 * here, so what they approve is exactly what a member gets. The backend
 * decides what each caller may see; this file renders what it is given.
 *
 * Consumer clarity
 * ----------------
 * Every Offering is a **digital download**, and the page says so three
 * times over, because the cover images show physical-looking objects —
 * a tablet, headphones, a stack of books. Those are illustrations of a
 * mood, not photographs of a product, and a buyer must never be able to
 * conclude that a parcel is coming:
 *
 *   * a "Digital download" badge on the cover itself;
 *   * an explicit line stating that nothing is posted;
 *   * a caption under the cover naming it as an illustration.
 *
 * No purchase controls
 * --------------------
 * Acquisition does not exist yet (Phase D), so this page shows the
 * price and no way to pay it. A disabled "Buy" button would still be a
 * promise; the honest answer is a sentence saying buying is not open.
 * A member who already owns the Offering sees their downloads instead.
 */
export default async function MemberOfferingPage({ params }: Props) {
  const { slug, offeringSlug } = await params
  const offering: MemberOffering | null = await getMemberOffering(slug, offeringSlug)

  // Covers both "no such Offering" and "a draft somebody else owns" —
  // the backend returns 404 for each, so a stranger cannot tell them
  // apart.
  if (!offering) notFound()

  const cover = resolveMediaUrl(offering.cover_image_url ?? undefined)
  const price = priceLabel(offering)
  const isDraft = offering.status === 'draft'
  const isRetired = offering.status === 'retired'
  const palette: CollectivePaletteMeta | null =
    offering.collective.colour_palette ?? null

  return (
    <div className="mx-auto w-full max-w-[1100px] px-5 py-8 md:px-8 md:py-12">
      {/* Manager-only banner. A member never sees this. */}
      {offering.viewer_manages && (isDraft || isRetired) && (
        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3">
          <p className="text-[13.5px] font-semibold text-[#7A5A00]">
            {isDraft ? 'Draft — only you can see this' : 'Retired — no longer offered'}
          </p>
          <p className="mt-0.5 text-[13px] text-[#6B4F00]">
            {isDraft
              ? 'This is exactly how it will look once published.'
              : 'People who already have it keep their files.'}
          </p>
        </div>
      )}

      <Link
        href={`/spaces/${slug}`}
        className="text-[13px] text-teal-700 underline-offset-2 hover:underline"
      >
        ← {offering.collective.name}
      </Link>

      <div className="mt-5 grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        {/* ── Main column ──────────────────────────────────────────── */}
        <div className="min-w-0">
          {/* Cover */}
          <figure className="m-0">
            <div
              className="relative overflow-hidden rounded-2xl"
              style={{ aspectRatio: '3 / 2', background: '#F4F7F6' }}
            >
              {cover ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={cover}
                  alt=""
                  className="h-full w-full object-cover"
                />
              ) : (
                <div
                  className="h-full w-full"
                  style={{ background: 'linear-gradient(135deg, rgba(56,160,158,0.16) 0%, rgba(85,184,182,0.08) 100%)' }}
                  aria-hidden="true"
                />
              )}
              <span
                className="absolute left-4 top-4 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]"
                style={{
                  background: 'rgba(255,255,255,0.94)',
                  color: '#0f766e',
                  backdropFilter: 'blur(6px)',
                }}
              >
                Digital download
              </span>
            </div>
            {/* The cover is mood, not merchandise. Said plainly, under
                the image, where somebody looking at a photographed
                object will read it. */}
            <figcaption
              className="mt-2 text-[12px] italic"
              style={{ color: 'rgba(12,24,38,0.5)' }}
            >
              Cover illustration. Any objects shown are not part of this
              Offering.
            </figcaption>
          </figure>

          <h1 className="mt-6 font-serif text-[30px] leading-tight md:text-[36px]" style={{ color: '#0C1826' }}>
            {offering.title}
          </h1>

          {offering.creator?.name && (
            <p className="mt-2 text-[14px]" style={{ color: 'rgba(12,24,38,0.6)' }}>
              by {offering.creator.name} · {offering.collective.name}
            </p>
          )}

          {offering.summary && (
            <p
              className="mt-4 text-[17px] leading-relaxed"
              style={{ color: 'rgba(12,24,38,0.75)', fontFamily: 'Georgia, serif' }}
            >
              {offering.summary}
            </p>
          )}

          {offering.description && (
            <div className="mt-5 whitespace-pre-wrap text-[15px] leading-relaxed text-black">
              {offering.description}
            </div>
          )}

          {/* Rich content — the same renderer a Pathway About page uses. */}
          {offering.about_blocks.length > 0 && (
            <div className="mt-8 space-y-6">
              {offering.about_blocks.map((block) => (
                <AboutBlockRenderer
                  key={block.id}
                  block={block}
                  collectivePalette={palette}
                />
              ))}
            </div>
          )}

          {/* ── What's included ─────────────────────────────────────── */}
          <section className="mt-10">
            <h2 className="text-[18px] font-semibold text-navy-900">
              What&rsquo;s included
            </h2>
            <p className="mt-1 text-[13.5px]" style={{ color: 'rgba(12,24,38,0.6)' }}>
              {offering.file_count === 0
                ? 'No files have been added yet.'
                : `${offering.total_resources} file${offering.total_resources === 1 ? '' : 's'} to download and keep.`}
            </p>

            {offering.files.length > 0 && (
              <ul className="mt-4 space-y-2.5">
                {offering.files.map((f) => (
                  <li
                    key={f.id}
                    className="rounded-xl border border-slate-200 bg-white px-4 py-3"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="min-w-0 text-[14px] font-medium text-navy-900">
                        {f.name}
                      </p>
                      <span
                        className="shrink-0 text-[12px]"
                        style={{ color: 'rgba(12,24,38,0.55)' }}
                      >
                        {f.type_label} · {f.size_label}
                        {f.resource_count > 1 && ` · ${f.resource_count} files inside`}
                      </span>
                    </div>
                    {f.description && (
                      <p className="mt-1 text-[13px] leading-relaxed" style={{ color: 'rgba(12,24,38,0.68)' }}>
                        {f.description}
                      </p>
                    )}
                    {f.download_url && (
                      <a
                        href={f.download_url}
                        className="mt-2 inline-flex items-center rounded-lg px-3 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                        style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                      >
                        Download
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {/* The sentence that removes all doubt. */}
            <p
              className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13px] leading-relaxed"
              style={{ color: 'rgba(12,24,38,0.72)' }}
            >
              This is a digital download. Everything above is a file you
              download and keep — nothing physical is posted to you.
            </p>
          </section>
        </div>

        {/* ── Sidebar ──────────────────────────────────────────────── */}
        <aside className="lg:sticky lg:top-8 lg:self-start">
          <div
            className="rounded-2xl bg-white p-5"
            style={{
              border: '1px solid rgba(12, 24, 38, 0.08)',
              boxShadow: '0 6px 20px rgba(12, 24, 38, 0.06)',
            }}
          >
            {price && (
              <p className="font-serif text-[28px] leading-none" style={{ color: '#0C1826' }}>
                {price}
              </p>
            )}

            <p className="mt-2 text-[13px]" style={{ color: 'rgba(12,24,38,0.6)' }}>
              Digital download
              {offering.total_resources > 0 && (
                <> · {offering.total_resources} file{offering.total_resources === 1 ? '' : 's'}</>
              )}
            </p>

            {offering.viewer_owns ? (
              <div className="mt-4 rounded-xl border border-teal-200 bg-teal-50/60 px-3 py-2.5">
                <p className="text-[13.5px] font-semibold text-teal-800">
                  You have this
                </p>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-teal-900/80">
                  Your downloads are listed on this page. If the creator
                  updates a file, you get the new version at no extra cost.
                </p>
              </div>
            ) : (
              /* No purchase control. Acquisition is not built, and a
                 disabled button would still read as a promise. */
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
                <p className="text-[13px] leading-relaxed" style={{ color: 'rgba(12,24,38,0.7)' }}>
                  {isRetired
                    ? 'This Offering is no longer available.'
                    : 'Buying isn’t open yet. Check back soon.'}
                </p>
              </div>
            )}

            <dl className="mt-4 space-y-2 border-t border-slate-100 pt-4">
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>Format</dt>
                <dd className="text-[12.5px] font-medium text-navy-900">
                  Digital download
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>From</dt>
                <dd className="text-[12.5px] font-medium text-navy-900">
                  <Link href={`/spaces/${slug}`} className="hover:underline">
                    {offering.collective.name}
                  </Link>
                </dd>
              </div>
            </dl>
          </div>
        </aside>
      </div>
    </div>
  )
}
