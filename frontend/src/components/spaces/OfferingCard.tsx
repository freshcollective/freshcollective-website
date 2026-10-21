import Link from 'next/link'
import { resolveMediaUrl } from '@/lib/api'
import type { OfferingCard as OfferingCardData } from '@/types/platform'

interface Props {
  offering: OfferingCardData
  spaceSlug: string
}

/**
 * One Offering in a Collective's catalogue.
 *
 * Deliberately the same shape, radius, border, hover lift and cover
 * aspect as ``PathwayCard``: an Offering is another thing a Collective
 * holds, not an arrival in a different kind of shop. The only structural
 * difference is the price, which sits in the footer where a Pathway puts
 * its access badge.
 *
 * Two honesty rules the card has to carry
 * ---------------------------------------
 *
 * The cover images show physical-looking objects — a tablet, headphones,
 * a stack of books — because they are illustrations of a mood. So the
 * card states "Digital download" on the image itself, and the category
 * beside it is derived from the actual files rather than from the
 * artwork. A card for a PDF workbook that happens to use the audio
 * cover still reads "PDF".
 *
 * And an Offering the viewer already owns says so instead of showing a
 * price. Nobody should have to remember whether they bought something.
 */
export default function OfferingCard({ offering, spaceSlug }: Props) {
  const href = `/spaces/${spaceSlug}/offerings/${offering.slug}`
  const cover = resolveMediaUrl(offering.cover_image_url ?? undefined)
  const owned = offering.viewer_owns

  const resourceLabel = offering.total_resources === 1
    ? '1 file'
    : `${offering.total_resources} files`

  return (
    <Link
      href={href}
      className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-sm transition-all hover:-translate-y-1 hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.20))] hover:shadow-lg"
    >
      {/* Cover — 3:2, matching the member detail page so the image a
          creator chose is not cropped differently in two places. */}
      <div
        className="relative overflow-hidden"
        style={{ aspectRatio: '3 / 2', background: '#F4F7F6' }}
      >
        {cover ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={cover}
            alt=""
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
          />
        ) : (
          /* A missing cover is a quiet gradient, never a broken image.
             The default cover assets are installed as a separate launch
             step, so this is the state the catalogue renders until then
             and it has to look deliberate. */
          <div
            className="h-full w-full"
            style={{ background: 'linear-gradient(135deg, rgba(56,160,158,0.16) 0%, rgba(85,184,182,0.08) 100%)' }}
            aria-hidden="true"
          />
        )}
        <span
          className="absolute left-3 top-3 rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-[0.12em]"
          style={{
            background: 'rgba(255,255,255,0.94)',
            color: '#0f766e',
            backdropFilter: 'blur(6px)',
          }}
        >
          Digital download
        </span>
        {owned && (
          <span
            className="absolute right-3 top-3 rounded-full px-2.5 py-1 text-[10.5px] font-semibold"
            style={{ background: '#0f766e', color: '#FFFFFF' }}
          >
            In Your Collection
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col p-4">
        <h3 className="mb-1.5 text-[15px] font-semibold leading-snug text-navy-900">
          {offering.title}
        </h3>

        {offering.summary ? (
          <p className="mb-4 flex-1 text-[13px] leading-relaxed text-black line-clamp-2">
            {offering.summary}
          </p>
        ) : (
          <div className="flex-1" />
        )}

        <div className="flex items-baseline justify-between gap-3 border-t border-slate-100 pt-3">
          <span
            className="text-[12px]"
            style={{ color: 'rgba(12,24,38,0.58)' }}
          >
            {offering.category_label}
            {offering.total_resources > 0 && <> · {resourceLabel}</>}
          </span>
          {owned ? (
            <span className="text-[13px] font-semibold text-teal-700">
              Open
            </span>
          ) : (
            offering.price_label && (
              <span className="text-[14px] font-semibold text-navy-900">
                {offering.price_label}
              </span>
            )
          )}
        </div>
      </div>
    </Link>
  )
}
