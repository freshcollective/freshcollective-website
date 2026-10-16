/**
 * CountBadge — the small filled disc that says "there is something
 * here".
 *
 * Extracted from the two inline copies in ``SpaceNav``, which had
 * drifted: the desktop one capped at ``9+`` and the mobile one at
 * ``9``, losing the plus exactly where space is tightest and the
 * distinction matters most. One definition, one cap.
 *
 * The personal bell keeps its own ``99+`` — a different surface with
 * a different ceiling, deliberately left alone.
 *
 * Three variants, one set of rules. ``inline`` and ``corner`` sit on
 * flat navigation chrome. ``card`` lies over Location artwork — on
 * Your World and on the Collective Home tiles — so it is larger and
 * carries a white keyline, because a teal disc on a teal-green
 * headland is not a signal. The cap, the zero rule, the colour and
 * the spoken sentence are shared by all three: a badge may look
 * different on artwork, but it may not *say* anything different.
 *
 * Accessibility: the digit is decorative. "3" sitting beside
 * "Pathways" is ambiguous read aloud, so the number is hidden from
 * assistive technology and a full sentence is provided instead.
 */

const CAP = 9

interface Props {
  count: number
  /** Inline after a label (desktop tabs), pinned to an icon (mobile
   *  bottom nav), or laid over artwork (``card`` — Your World cards
   *  and Collective Home tiles, both positioned by their parent). */
  variant?: 'inline' | 'corner' | 'card'
  /** Completes the sentence "{n} new …" — e.g. "in Pathways". */
  label: string
  className?: string
}

export default function CountBadge({
  count, variant = 'inline', label, className,
}: Props) {
  // Zero is absence, not a state to render. Never a "0", never a dot.
  if (!count || count < 1) return null

  const shown = count > CAP ? `${CAP}+` : String(count)

  const base =
    'flex items-center justify-center rounded-full font-bold text-white'
  const sizing =
    variant === 'corner'
      ? 'absolute -right-1.5 -top-1 h-3.5 min-w-[14px] px-[3px] text-[8px]'
      : variant === 'card'
        ? 'h-[22px] min-w-[22px] px-[5px] text-[12px]'
        : 'h-4 min-w-[16px] px-[3px] text-[9px]'

  return (
    <span
      className={[base, sizing, className].filter(Boolean).join(' ')}
      style={{
        background: 'var(--fc-accent, #38A09E)',
        // Artwork behind a badge can be any colour, including this
        // one. The keyline guarantees an edge; the shadow lifts the
        // disc off the image. Flat chrome needs neither, so the nav
        // variants are left exactly as they were.
        ...(variant === 'card'
          ? { boxShadow: '0 0 0 2px #fff, 0 1px 3px rgba(12, 24, 38, 0.28)' }
          : null),
      }}
    >
      <span aria-hidden="true">{shown}</span>
      <span className="sr-only">{`${count} new ${label}`}</span>
    </span>
  )
}
