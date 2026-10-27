import {
  SHOW_AROUND_LINK_LABEL,
  SHOW_AROUND_MAILTO,
  SHOW_AROUND_QUESTION,
} from '@/lib/showAroundInvitation'

/**
 * The 15-minute show-around invitation, rendered the same way in both
 * places it appears.
 *
 * A quiet question and a teal text link — the page's existing link
 * treatment, the one the For Creators About line and the About page's
 * video link already use. No button: under the homepage video the
 * video is the feature, and under the For Creators FAQ "Choose your
 * plan" is already the page's one primary action. A second button in
 * either place would argue with what is there.
 *
 * Spacing is the caller's, through ``className`` — the two hosts sit
 * in differently-spaced sections and neither should inherit the
 * other's margin.
 */

const TEAL_DEEP = '#246B6A'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

export default function ShowAroundInvitation({
  className,
}: {
  className?: string
}) {
  return (
    <div className={`text-center ${className ?? ''}`}>
      <p
        className="text-[14.5px] leading-relaxed"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        {SHOW_AROUND_QUESTION}
      </p>
      <p className="mt-1.5">
        <a
          href={SHOW_AROUND_MAILTO}
          className="rounded-sm text-[14.5px] underline decoration-1 underline-offset-4 transition-colors hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
          style={{ color: TEAL_DEEP, textDecorationColor: 'rgba(36,107,106,0.35)' }}
        >
          {SHOW_AROUND_LINK_LABEL}
        </a>
      </p>
    </div>
  )
}
