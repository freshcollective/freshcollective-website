/**
 * Public Creator plan metadata — presentation only.
 *
 * These values are what public marketing pages (/for-creators) and the
 * signup / checkout summaries display. They are NOT the source of truth
 * for any operational decision.
 *
 * Backend source of truth: `backend/app/creator/plan_config.py`. All
 * limits, permissions, transaction fees, entitlement enforcement, and
 * billing behaviour live there. If a value in this file ever disagrees
 * with the backend, the backend wins. Operational checks must never
 * import from this file.
 *
 * Keep public-facing copy here aligned with the backend by review, not
 * by shared code — the two live in different runtimes and are updated
 * on different cadences. When Stripe and a public plan-config endpoint
 * are wired, this file should be replaced by data fetched from that
 * endpoint so drift becomes structurally impossible.
 *
 * Ecosystem is intentionally absent: it is coming-soon and does not
 * enter any signup or checkout flow.
 */

export type CreatorPlanSlug = 'community' | 'creator' | 'pro'

export interface PublicPlanDisplay {
  /** Stable backend slug — must match a plan slug in plan_config.py. */
  slug: CreatorPlanSlug
  /** Public display name shown on marketing + signup pages. */
  displayName: string
  /** Short italic tagline used beneath the display name. */
  tagline: string
  /** Human price label, e.g. "Free", "$19 / month". Not used for any
   *  actual billing calculation. */
  priceLabel: string
  /**
   * The commission this plan takes on a paid sale, in basis points, or
   * null for a plan with no paid offers.
   *
   * Display only — checkout reads the ``creator_plans`` database row. The
   * point of holding it here is that every public surface reads the same
   * value, so the home page and /for-creators cannot drift apart.
   *
   * **Must equal the live database figure, not the intended one.** A public
   * page promising a lower commission than checkout charges is the worse of
   * the two possible errors, so this trails the database rather than leading
   * it: change the row first, then this.
   */
  commissionBasisPoints: number | null
  /** The same figure as a label, e.g. "8%". Null when there is no paid
   *  commission to state. */
  commissionLabel: string | null
  /** Where the /for-creators plan CTA sends the visitor. Community
   *  skips payment; paid plans go through /checkout/creator first. */
  ctaHref: string
  /** Short, concrete bullets shown on the /signup/creator summary
   *  card. Written so a visitor can see, at a glance, what they are
   *  starting with. */
  summaryBullets: string[]
  /** Platform Artwork key for this plan. The /for-creators, /checkout
   *  /creator and /signup/creator pages all render the same uploaded
   *  image via this key. Keys must exist in `PLATFORM_ARTWORK_KEYS`
   *  (backend/app/admin/platform_artwork.py). */
  artworkKey: string
  /** Atmosphere slug used for the gradient fallback when no artwork
   *  has been uploaded. Must match a slug in `placeAtmosphere`. */
  atmosphereSlug: string
  /** Editorial alt text for the plan artwork. */
  artworkAlt: string
}

/**
 * What Fresh Collective covers, stated once.
 *
 * Fresh Collective absorbs the card processing cost out of its own
 * commission, so a creator's earnings are the sale less the commission and
 * nothing else. Every public surface says it the same way, and deliberately
 * quotes no processing rate: a figure a creator never pays only invites them
 * to subtract it.
 */
export const PROCESSING_COVERED_LINE =
  'We cover standard card processing costs'

/** "8% commission on paid offers", or null for a plan without paid offers. */
export function commissionBullet(plan: PublicPlanDisplay): string | null {
  return plan.commissionLabel
    ? `${plan.commissionLabel} commission on paid offers`
    : null
}

/** "8% on paid transactions" — the shorter home-page phrasing. */
export function commissionBulletShort(plan: PublicPlanDisplay): string | null {
  return plan.commissionLabel
    ? `${plan.commissionLabel} on paid transactions`
    : null
}

export const PUBLIC_PLANS: Record<CreatorPlanSlug, PublicPlanDisplay> = {
  community: {
    slug: 'community',
    displayName: 'Community Collective',
    tagline: 'A first place to gather.',
    priceLabel: 'Free',
    // No paid offers on Community, so there is no commission to state.
    commissionBasisPoints: null,
    commissionLabel: null,
    ctaHref: '/signup/creator?plan=community',
    // Every bullet here is enforced server-side — see
    // backend/app/creator/plan_guards.py. "approved" was removed from the
    // first bullet because Community has `approval_required=False` and no
    // approval step exists anywhere in the platform; promising review we
    // do not perform is worse than promising nothing.
    summaryBullets: [
      'One Collective',
      'Up to 100 members',
      'Up to 5 Pathways',
      'For non-commercial gatherings',
      'World Builders Collective included',
    ],
    artworkKey: 'for_creators_community',
    atmosphereSlug: 'for-creators-community',
    artworkAlt:
      'A Community Collective on Fresh Collective — a shared table, a small local gathering',
  },
  creator: {
    slug: 'creator',
    displayName: 'Creator',
    tagline: 'Build your business.',
    priceLabel: '$19 / month',
    // 8% — matches the live ``creator_plans`` row.
    commissionBasisPoints: 800,
    commissionLabel: '8%',
    ctaHref: '/checkout/creator?plan=creator',
    summaryBullets: [
      'One commercial Collective',
      'Paid Pathways',
      'Paid Gatherings',
      'Paid Collective Memberships',
      'World Builders Collective included',
    ],
    artworkKey: 'for_creators_creator',
    atmosphereSlug: 'for-creators-creator',
    artworkAlt: 'A single creator at work — a studio, considered craft',
  },
  pro: {
    slug: 'pro',
    displayName: 'Creator Portfolio',
    tagline: 'Multiple Collectives. One Creator.',
    priceLabel: '$79 / month',
    // 4% — matches the live ``creator_plans`` row, changed in
    // World Management on 2026-10-11. Checkout reads that row per
    // transaction, so this constant exists only to publish the same
    // figure; it never decides what anyone is charged. If the two
    // ever disagree, ``publicPricingConsistency.test.ts`` fails.
    commissionBasisPoints: 400,
    commissionLabel: '4%',
    ctaHref: '/checkout/creator?plan=pro',
    summaryBullets: [
      'Up to 5 Collectives',
      'Commercial use',
      'Advanced analytics',
      'Multiple workspaces per Collective',
      'World Builders Collective included',
    ],
    artworkKey: 'for_creators_pro',
    atmosphereSlug: 'for-creators-pro',
    artworkAlt: 'Several Collectives thriving under one Creator — a connected landscape',
  },
}

/** Resolve a raw string (from a query param) to a known plan. Returns
 *  null for unknown or malformed values — callers should render a
 *  not-found state rather than assume a default. */
export function getPublicPlan(slug: string | null | undefined): PublicPlanDisplay | null {
  if (!slug) return null
  return slug in PUBLIC_PLANS ? PUBLIC_PLANS[slug as CreatorPlanSlug] : null
}
