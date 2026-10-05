/**
 * Who may enter Creator Studio. One definition.
 *
 * The rule already existed, written out twice — identically, in
 * ``app/creator-studio/layout.tsx`` and ``app/creator/layout.tsx``:
 *
 *     if (!['creator', 'admin'].includes(profile.role)) redirect('/dashboard')
 *
 * Adding a navigation doorway would have made three copies, and the way
 * a rule like that drifts is somebody writing the fourth from memory.
 * So it lives here and the guards call it.
 *
 * Why the role and not a plan
 * ---------------------------
 * ``role`` is the account's standing; a plan is what it pays for. Those
 * are different questions and only the first one decides entry:
 *
 *   * **Community creators** — activation is role-only and writes no
 *     subscription row at all, so a plan-based check would lock out the
 *     entire free tier.
 *   * **Paid Creator / Pro / Founding Creator** — all the same role.
 *     Their plan changes what Creator Studio *shows* (the commercial
 *     surface is gated separately on ``paid_offers_enabled``), never
 *     whether they can open it.
 *   * **Platform Owner** — an account/platform role, carried by
 *     ``admin``, which is why ``admin`` is in the set. It is not a plan,
 *     and keying on Founding Creator would have missed it.
 *   * **A future creator tier** — arrives with the creator role and is
 *     included without touching this file. That is the point of not
 *     enumerating slugs.
 *
 * So: no plan slugs, no hardcoded tier lists, and nothing that treats
 * ``role === 'creator'`` as sufficient on its own — ``admin`` would be
 * excluded, and the Platform Owner is an admin.
 */

/** The account roles that may open Creator Studio. */
export const CREATOR_STUDIO_ROLES = ['creator', 'admin'] as const

/**
 * Whether this account may enter Creator Studio.
 *
 * Takes only what it needs. A null or undefined user is not allowed —
 * a signed-out visitor has no standing, and defaulting the other way
 * would surface a doorway that leads straight to a redirect.
 */
export function canAccessCreatorStudio(
  user: { role?: string | null } | null | undefined,
): boolean {
  const role = user?.role
  if (!role) return false
  return (CREATOR_STUDIO_ROLES as readonly string[]).includes(role)
}

export const CREATOR_STUDIO_HREF = '/creator-studio'
