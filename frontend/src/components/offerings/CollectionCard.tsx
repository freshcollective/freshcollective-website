import Link from 'next/link'
import { resolveMediaUrl } from '@/lib/api'
import type { CollectionItem } from '@/types/platform'

interface Props {
  item: CollectionItem
}

/**
 * One acquired Offering in Your Collection.
 *
 * Shares its silhouette with ``OfferingCard`` — same radius, border,
 * cover ratio and hover — because it is the same object, now owned. The
 * footer is where they differ: a catalogue card shows a price, and this
 * one shows where it came from.
 *
 * Two states that must not be silent
 * ----------------------------------
 *
 * **Retired.** The creator has stopped offering it. The member still
 * owns it, so the card works exactly as before and says so quietly —
 * otherwise somebody who cannot find it in the catalogue any more is
 * left wondering whether they have lost it.
 *
 * **Files being updated.** A replacement mid-validation, or an operator
 * quarantine, leaves an owned Offering with nothing to download right
 * now. Saying that is kinder than a download that refuses them.
 */
export default function CollectionCard({ item }: Props) {
  const cover = resolveMediaUrl(item.cover_image_url ?? undefined)
  const retired = item.offering_status === 'retired'
  const href = item.href

  const resourceLabel = item.total_resources === 1
    ? '1 file'
    : `${item.total_resources} files`

  const inner = (
    <>
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
          <div
            className="h-full w-full"
            style={{ background: 'linear-gradient(135deg, rgba(56,160,158,0.16) 0%, rgba(85,184,182,0.08) 100%)' }}
            aria-hidden="true"
          />
        )}
        {retired && (
          <span
            className="absolute left-3 top-3 rounded-full px-2.5 py-1 text-[10.5px] font-semibold"
            style={{ background: 'rgba(255,255,255,0.94)', color: '#6B4F00' }}
          >
            No longer offered
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col p-4">
        <h3 className="mb-1.5 text-[15px] font-semibold leading-snug text-navy-900">
          {item.title}
        </h3>

        {item.summary ? (
          <p className="mb-4 flex-1 text-[13px] leading-relaxed text-black line-clamp-2">
            {item.summary}
          </p>
        ) : (
          <div className="flex-1" />
        )}

        {!item.files_available && (
          <p
            className="mb-3 rounded-lg px-2.5 py-2 text-[12px] leading-relaxed"
            style={{
              background: 'rgba(122,90,0,0.06)',
              color: '#6B4F00',
            }}
          >
            The files are being updated. They&rsquo;ll be back shortly —
            this stays yours.
          </p>
        )}

        <div className="border-t border-slate-100 pt-3">
          <p className="text-[12px]" style={{ color: 'rgba(12,24,38,0.58)' }}>
            {item.category_label}
            {item.total_resources > 0 && <> · {resourceLabel}</>}
          </p>
          {item.collective && (
            <p className="mt-1 text-[12px]" style={{ color: 'rgba(12,24,38,0.58)' }}>
              {item.collective.name}
              {item.creator_name && <> · {item.creator_name}</>}
            </p>
          )}
        </div>
      </div>
    </>
  )

  const cardClass = 'group flex flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-sm'

  // No link when the Collective is gone — the detail page lives under
  // its slug, so there is nowhere to send them. The card still shows
  // what they own rather than disappearing.
  if (!href) {
    return <div className={cardClass}>{inner}</div>
  }

  return (
    <Link
      href={href}
      className={`${cardClass} transition-all hover:-translate-y-1 hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.20))] hover:shadow-lg`}
    >
      {inner}
    </Link>
  )
}
