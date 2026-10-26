/**
 * Rendering a public About page from the allowlisted public payload.
 *
 * World Builders is discoverable on Explore and private inside. A
 * prospective creator has to be able to read what it offers before
 * becoming one — but its ``GET /api/spaces/{slug}`` answers 404 to
 * them now that ``visibility='private'`` is enforced, and relaxing
 * that gate would have handed an anonymous caller the guidance bodies,
 * the Pathway list, the joining options and the member counts.
 *
 * So the server serves an explicit allowlist
 * (``spaces.schemas.PublicCollectiveAbout``) and this adapts it to the
 * shape the existing About page already reads. No second page, no
 * second design — the page renders a public visitor's view of a
 * private Collective the same way it renders an anonymous visitor's
 * view of a public one.
 *
 * Why an adapter rather than widening the page's own types: the
 * omissions have to be deliberate and testable. Every private field is
 * pinned to a safe empty value **here**, in one function, where a test
 * can assert what it refuses to carry — rather than being spread
 * across a component that would quietly render whatever it was handed.
 */

import type { PublicCollectiveAbout, SpaceResponse } from '@/types/platform'

/**
 * Fields a public About view must never carry, whatever the server
 * sends. Asserted by name in ``publicCollectiveAbout.test.ts``.
 *
 * ``guidance_*`` is the member-only material; ``welcome_message`` is
 * written for somebody who has already arrived; ``home_tiles`` and
 * ``area_access`` are a map of the inside; ``pathways`` and
 * ``joining_options`` are the protected resources and a door that does
 * not exist here; the counts are membership data.
 */
export const PRIVATE_ONLY_FIELDS = [
  'guidance_start_title',
  'guidance_start_body',
  'guidance_focus_title',
  'guidance_focus_body',
  'guidance_links_title',
  'guidance_links_body',
  'welcome_message',
  'identity_statement',
  'home_tiles',
  'area_access',
  'joining_options',
  'learner_count',
  'leader_count',
  'upcoming_gathering_count',
  'next_gathering_starts_at',
  'published_offering_count',
  'show_member_directory',
  'area_access',
] as const

/**
 * The public payload, in the shape the About page reads.
 *
 * ``pathways`` is an empty list rather than omitted: the page uses it
 * only to build a "paid separately" summary for ``purchase_required``
 * Collectives, and an empty list produces no summary — which is right,
 * because a Collective with no public joining has nothing to sell on
 * top of it.
 *
 * ``is_public`` is reported as ``false`` because it is: the page shows
 * a 🔒 Private chip from it, which is an honest thing for a visitor to
 * see on a Collective they cannot enter.
 */
export function publicAboutAsSpace(
  about: PublicCollectiveAbout,
): SpaceResponse {
  return {
    // Not the real database id. The About page never uses it, and
    // handing out an internal identifier on a public surface has no
    // upside.
    id: '',
    slug: about.slug,
    name: about.name,
    tagline: about.tagline,
    description: about.description,
    about_content: about.about_content,
    is_public: false,
    auto_grant_role: about.creator_only ? 'creator' : null,
    status: 'active',
    timezone: 'UTC',
    cover_image_url: about.cover_image_url,
    logo_url: about.logo_url,
    pathways: [],
    pricing_type: 'free',
    pricing_amount_cents: null,
    pricing_currency: 'AUD',
    pricing_note: null,
    has_paid_internal_content: false,
    included_access_summary: null,
    paid_content_summary: null,
    derived_has_paid_internal_content: false,
    min_paid_pathway_price_cents: null,
    creator_name: about.creator_name,
    // The Location, for the page's own artwork. ``id`` and ``key`` are
    // blanked rather than carried: the page renders the name and the
    // two artwork URLs and nothing else, and an Atlas identifier is
    // not a visitor's business.
    location: (
      about.location_hero_artwork_url
      || about.location_thumbnail_artwork_url
      || about.location_name
    )
      ? {
          id: '',
          key: '',
          name: about.location_name ?? '',
          description: null,
          hero_artwork_url: about.location_hero_artwork_url,
          thumbnail_artwork_url: about.location_thumbnail_artwork_url,
        }
      : null,
    // ``JoinPolicy`` is 'open' | 'purchase_required' — there is no
    // "no public joining" value, because for an ordinary Collective
    // there always is one. 'open' is the safe choice of the two: it
    // makes the page render no purchase copy and no price, and the
    // join action itself is not offered to a non-member anyway. The
    // real refusal is the server's — ``join_space`` answers 403 for an
    // auto-grant Collective unconditionally, and ``request_access``
    // now does too.
    join_policy: 'open',

    // ── The private fields, nulled explicitly ────────────────────────
    //
    // ``SpaceResponse`` requires these, and that is useful: setting
    // each to null by hand is an affirmative statement that a public
    // visitor gets none of it, and the compiler fails this function if
    // a new required field is added without a decision being made
    // about it. ``PRIVATE_ONLY_FIELDS`` and its test assert the result.
    guidance_start_title: null,
    guidance_start_body: null,
    guidance_focus_title: null,
    guidance_focus_body: null,
    guidance_links_title: null,
    guidance_links_body: null,
    welcome_message: null,
    identity_statement: null,
    learner_count: 0,
    leader_count: 0,
    // The directory is not offered to a visitor at all; false is the
    // closed value, and the members endpoint refuses them regardless.
    show_member_directory: false,
    // **Empty, and this one matters.** ``SpaceNav`` treats
    // ``reachableAreas === undefined`` as "show every tab", so leaving
    // this off rendered Pathways, Gatherings, Conversations, Messages
    // and Members in the nav for a public visitor to a private
    // Collective. Every one of them refuses on click — the backend is
    // closed — but offering a door that cannot open is exactly the
    // "About page becoming a doorway into protected resources" this
    // release is meant to avoid.
    //
    // An empty list is the honest answer: a visitor reaches no area of
    // this Collective. ``about`` is not listed because no route gates
    // on it and the nav has no tab for it.
    area_access: [],
  }
}

/** Copy for the visitor's call to action on a creator-only Collective. */
export const PUBLIC_ABOUT_CTA_LABEL = 'Explore Becoming a Creator →'
export const PUBLIC_ABOUT_CTA_HREF = '/for-creators'
