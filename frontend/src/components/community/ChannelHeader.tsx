/**
 * ChannelHeader — the calm, spacious header shown above every feed.
 *
 * Renders the channel's icon, name and (optional) description as a
 * single quiet block so members always know which room they've walked
 * into. Server component: no interactivity, no state.
 */

interface Props {
  icon: string | null
  name: string
  description: string | null
  archived?: boolean
}

export default function ChannelHeader({ icon, name, description, archived }: Props) {
  return (
    <div className="mb-5">
      <div className="flex items-baseline gap-2.5">
        {icon && (
          <span aria-hidden="true" className="text-[22px] leading-none">
            {icon}
          </span>
        )}
        <h2 className="font-serif text-[22px] leading-tight text-navy-900">
          {name}
        </h2>
        {archived && (
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
            style={{ background: 'rgba(212,176,72,0.14)', color: '#8A6A15' }}
          >
            Archived
          </span>
        )}
      </div>
      {description && (
        <p
          className="mt-1.5 text-[13.5px] leading-relaxed italic"
          style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}
        >
          {description}
        </p>
      )}
    </div>
  )
}
