/**
 * FIP4B1 — member payment-plan recovery banner.
 *
 * Renders TWO calm, non-alarming states:
 *
 *   ``payment_problem`` — the member's card failed on their most
 *   recent instalment but access remains active during the 7-day
 *   grace window. Shows the grace deadline formatted in the
 *   Collective timezone and prompts the member to update payment
 *   details "before <date>".
 *
 *   ``suspended`` — grace expired without recovery, access is
 *   paused. Shows a firmer but still non-punitive recovery message
 *   and directs the member to update payment details.
 *
 * The actual "update payment details" action is FIP4B2. This
 * component renders a placeholder disabled button for local dev
 * review — no broken action is ever exposed. When FIP4B2 lands,
 * swap the placeholder for the real repair-flow CTA.
 *
 * Copy is intentionally warm and calm — no red banners, no scary
 * language. This is a member who almost certainly wants to fix
 * their card and continue.
 */

import type { MemberPlanState } from '@/types/platform'
import { planRecoveryCopy } from '@/lib/planRecoveryCopy'

interface Props {
  state: MemberPlanState
  /** Space timezone (from ``SpaceResponse.timezone``). Used to
   *  format ``grace_expires_at`` so the date matches the
   *  Collective's local frame. Falls back to browser locale if
   *  unset. */
  timezone?: string | null
}

export function PlanRecoveryBanner({ state, timezone }: Props) {
  const isSuspended = state.status === 'suspended'
  const copy = planRecoveryCopy(state, timezone)

  // Palette — soft amber for grace, warmer terracotta for suspended.
  // Neither is red; both stay inside the Fresh Collective feel.
  const palette = isSuspended
    ? { bg: 'rgba(180, 83, 9, 0.06)', border: 'rgba(180, 83, 9, 0.24)', accent: '#B45309' }
    : { bg: 'rgba(212, 176, 72, 0.10)', border: 'rgba(212, 176, 72, 0.30)', accent: '#8A6A15' }

  // The FIP4B2 repair Checkout Session doesn't exist yet — a
  // non-functional CTA must never reach production. Render the
  // disabled placeholder only in development/test so local review
  // can still preview it; in production, fall back to a plain
  // text line so the banner still tells the member what's coming.
  const showPlaceholderCta = process.env.NODE_ENV !== 'production'

  return (
    <div
      className="rounded-2xl px-5 py-4"
      style={{
        background: palette.bg,
        border: `1px solid ${palette.border}`,
      }}
      role="status"
    >
      <p
        className="mb-1 text-[13px] font-semibold"
        style={{ color: palette.accent }}
      >
        {copy.headline}
      </p>
      <p className="text-[13px] leading-relaxed text-navy-900">
        {copy.body}
      </p>
      <p className="mt-1 text-[11px] text-slate-500">
        {copy.progress}
      </p>
      {showPlaceholderCta ? (
        <button
          type="button"
          disabled={copy.ctaDisabled}
          className="mt-3 inline-flex items-center rounded-full px-4 py-2 text-[12px] font-semibold text-white opacity-70 cursor-not-allowed"
          style={{
            background: palette.accent,
          }}
          aria-disabled={copy.ctaDisabled ? 'true' : 'false'}
          title="Coming soon in the next milestone (dev-only placeholder)"
        >
          {copy.cta}
        </button>
      ) : (
        <p className="mt-3 text-[12px] font-medium text-slate-500">
          Update payment details — coming soon.
        </p>
      )}
    </div>
  )
}
