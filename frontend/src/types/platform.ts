export interface PathwaySummary {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  status: 'draft' | 'active' | 'coming_soon' | 'archived'
  position: number
  access_type: 'free' | 'included' | 'one_time' | 'subscription' | 'included_with_offer' | 'included_with_offer'
  pricing_mode: 'legacy' | 'payment_options'
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
  /** How members experience this pathway. Defaults to
   *  'guided_experience' for every existing pathway. */
  pathway_type?: 'guided_experience' | 'knowledge_guide'
  user_has_access: boolean
  step_count: number
  unlock_offer_names: string[]
}

export interface SpaceResponse {
  id: string
  slug: string
  name: string
  tagline: string | null
  description: string | null
  about_content: string | null
  is_public: boolean
  /** When non-null, membership is auto-managed by Fresh Collective —
   *  join / request-access are hidden and settings are locked. Currently
   *  only used by the World Builders collective ('creator'). */
  auto_grant_role?: string | null
  status: string
  timezone: string
  cover_image_url: string | null
  /** Optional "hosted by" mark shown subtly beside the collective name. */
  logo_url?: string | null
  pathways: PathwaySummary[]
  pricing_type: PricingType
  pricing_amount_cents: number | null
  pricing_currency: string
  pricing_note: string | null
  has_paid_internal_content: boolean
  included_access_summary: string | null
  paid_content_summary: string | null
  derived_has_paid_internal_content: boolean
  guidance_start_title: string | null
  guidance_start_body: string | null
  guidance_focus_title: string | null
  guidance_focus_body: string | null
  guidance_links_title: string | null
  guidance_links_body: string | null
  show_member_directory: boolean
  /** Authoritative counts injected by the ``get_space`` endpoint. Use
   *  these for sidebar/stats displays — do NOT derive counts from
   *  the ``/api/spaces/{slug}/members`` list, which is privacy-
   *  filtered for learner-role viewers. */
  learner_count: number
  leader_count: number
  /** Atlas v1.2 — the collective's assigned Location (hydrated by the
   *  space detail endpoint). Consumers prefer the thumbnail for cards
   *  and the hero for large previews. */
  location?: {
    id: string
    key: string
    name: string
    description: string | null
    hero_artwork_url: string | null
    thumbnail_artwork_url: string | null
    /** Long-form Atlas Entry from World Management — read-only in
     *  Creator Studio; helps the Creator understand the feeling and
     *  story of the chosen island. Editing lives in /admin/atlas. */
    atlas_entry?: string | null
  } | null
  /** Atlas v1.2 — the chosen Colour Palette drives collective-scoped CSS
   *  custom properties. Hydrated by the space detail endpoint. */
  colour_palette?: {
    key: string
    name: string
    palette: { primary: string; secondary: string; accent: string; background: string }
  } | null
  colour_palette_key?: string | null
  atmosphere_keys?: string[]
  /** Resolved atmosphere display names in the creator-authored order. */
  atmosphere_labels?: string[]
  identity_statement?: string | null
  welcome_message?: string | null
}

export interface SpaceSummary {
  id: string
  slug: string
  name: string
  tagline: string | null
  status: string
  is_public: boolean
}

export type ReleaseType =
  | 'immediate'
  | 'days_after_enrollment'
  | 'fixed_date'
  | 'after_previous'
  | 'manual'

export interface StepAvailability {
  is_locked: boolean
  reason: ReleaseType | null
  unlocks_at: string | null
  message: string | null
  release_type: ReleaseType
  release_offset_days: number | null
  release_at: string | null
  release_timezone: string | null
  release_previous_state: 'completed' | 'started'
}

export interface StepSummary {
  id: string
  slug: string
  title: string
  content_type: string
  estimated_minutes: number | null
  is_required: boolean
  position: number
  is_completed: boolean
  banner_image_url?: string | null
  availability?: StepAvailability
}

export interface StepDetail extends StepSummary {
  content_body: string | null
  content_url: string | null
  reflection_text: string | null
  reflection_enabled: boolean
  discussion_enabled: boolean
  /** Set only when this step is the FIRST step in its section. */
  section_banner_image_url?: string | null
  /** Set only when this step is the FIRST step in its section. */
  section_title?: string | null
  /** Availability is always present on member-facing StepDetail responses. */
  availability?: StepAvailability
}

export interface PathwaySection {
  id: string
  /** URL-safe chapter identifier — the Knowledge Guide chapter
   *  switcher's `?section=` value. Empty string on older backend
   *  responses; the chapter helper handles that case. */
  slug?: string
  title: string
  position: number
  steps: StepSummary[]
  banner_image_url?: string | null
}

export interface PaymentOptionScheduleSummary {
  id: string
  name: string
  description: string | null
  schedule_type: 'pay_in_full' | 'recurring_installments' | 'manual'
  status: string
  total_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  buyer_note: string | null
  position: number
  /** Backend-authoritative flag from
   *  ``_schedule_is_member_checkoutable``. When ``false`` the
   *  member surface must hide the schedule. Never re-derived on
   *  the frontend. */
  is_member_checkoutable: boolean
}

export interface PaymentOptionSummary {
  id: string
  name: string
  description: string | null
  payment_type: 'free' | 'one_time' | 'term_pass' | 'subscription'
  status: string
  term_start_date: string | null
  term_end_date: string | null
  sessions_per_week: number | null
  total_sessions: number | null
  price_per_session_cents: number | null
  calculated_total_cents: number | null
  override_total_cents: number | null
  effective_price_cents: number | null
  currency: string
  buyer_note: string | null
  position: number
  schedules: PaymentOptionScheduleSummary[]
}

/** FIP4B1 — the viewer's own finite-plan agreement over this
 *  Pathway / Series, populated only when the plan needs the
 *  member's attention (payment_problem / suspended). Absent for
 *  active/completed plans, non-holders, and anonymous viewers. */
export interface MemberPlanState {
  /** PurchasePlan id. Passed to POST /api/finite-plan/repair-session
   *  to start the FIP4B2 repair Checkout Session. The backend
   *  re-validates ownership + recoverable status; the id is only a
   *  hint from the client, never an authority. */
  id: string
  status: 'payment_problem' | 'suspended'
  payment_option_name: string | null
  installments_paid: number
  installments_expected: number
  grace_expires_at: string | null
  suspended_at: string | null
  recovery_required: boolean
}

export interface PathwayWithSteps {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  status: string
  step_count: number
  completed_count: number
  steps: StepSummary[]
  sections: PathwaySection[]
  access_type: 'free' | 'included' | 'one_time' | 'subscription' | 'included_with_offer'
  pricing_mode: 'legacy' | 'payment_options'
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
  /** Presentation type — the pathway landing branches on this to
   *  render either the Guided step list or the Knowledge Guide
   *  continuous document. Defaults server-side to
   *  'guided_experience'. */
  pathway_type?: 'guided_experience' | 'knowledge_guide'
  user_has_access: boolean
  payment_options: PaymentOptionSummary[]
  /** FIP4B1 — surfaces the plan-recovery banner and suppresses
   *  standard purchase CTAs when present. */
  member_plan_state?: MemberPlanState | null
}

/** Knowledge Guide continuous-document payload — returned by
 *  ``GET /api/spaces/{slug}/pathways/{pathway_slug}/guide``. Only
 *  valid for Knowledge Guide pathways; the endpoint returns 409 for
 *  Guided Experience pathways. */
export interface KnowledgeGuide {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  pathway_type: 'knowledge_guide'
  orphan_steps: KnowledgeGuideStep[]
  sections: KnowledgeGuideSection[]
}

export interface KnowledgeGuideSection {
  id: string
  slug: string
  title: string
  banner_image_url: string | null
  steps: KnowledgeGuideStep[]
}

export interface KnowledgeGuideStep {
  id: string
  slug: string
  title: string
  /** Same block shape the per-step endpoint returns — rendered by
   *  the shared BlockList so guided and guide surfaces stay
   *  identical at the block level. */
  blocks: unknown[]
}

export interface CreatorSection {
  id: string
  pathway_id: string
  title: string
  position: number
  banner_image_url?: string | null
  created_at: string
}

export interface PathwayProgress {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  status: 'draft' | 'active' | 'coming_soon' | 'archived'
  position: number
  step_count: number
  completed_count: number
  access_type: 'free' | 'included' | 'one_time' | 'subscription' | 'included_with_offer'
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
}

export interface EventSummary {
  id: string
  title: string
  description: string | null
  starts_at: string
  ends_at: string | null
  location_type: 'zoom' | 'in_person' | 'async_recorded'
  requires_booking: boolean
  capacity: number | null
  booked_count: number
  spots_remaining: number | null
  booking_closes_at: string | null
  booking_note: string | null
  my_booking_status: 'confirmed' | 'cancelled' | 'pending_payment' | null
  can_book: boolean
  can_cancel_booking: boolean
  recurrence_series_id: string | null
  recurrence_label: string | null
  recurrence_index: number | null
  recurrence_total: number | null
  /** Semantic Gathering Series membership (migration 105). Populated
   *  by the backend when the Event belongs to a Series; ``series_title``
   *  is a hydrated convenience so the ACCESS row can render "Included
   *  with {series_title}" without a second fetch. */
  series_id: string | null
  series_title: string | null
  series_slug?: string | null
  /** Cover art for the parent Series. Used as a hero-image fallback
   *  when the Event has no ``thumbnail_url``. */
  series_cover_image_url?: string | null
  /** Slug of the *published* Offer Page targeting this Event's Series,
   *  if one exists. Lets a "Buy series pass" CTA route to the right
   *  public page without a second round-trip. */
  series_offer_page_slug?: string | null
  /** True when the viewer holds a valid, in-window Series pass
   *  scoped to this Event's series. Lets the booking UI show the
   *  correct state (Reserve vs Pass required) without triggering a
   *  speculative POST. */
  user_has_series_pass?: boolean
  is_public: boolean
  thumbnail_url: string | null
  status: 'active' | 'cancelled' | 'archived'
  /** Gatherings 2.0 vocabulary; see `lib/gatheringTypes.ts`. Legacy
   *  values ('all_members', 'pathway_required') are normalised
   *  server-side and will not appear on new responses. */
  booking_access_type: string
  booking_required_pathway_id: string | null
  user_has_pathway_access: boolean
  pass_credits_remaining?: number | null
  /** Gathering identity + attendance metadata. */
  gathering_type: string
  attendance_format: 'online' | 'in_person' | 'hybrid'
  venue_name: string | null
  /** Member-safe locality (suburb + region) derived server-side
   *  from ``venue_address``; always exposed. Filters out street-
   *  address fragments — see ``_derive_venue_locality`` on the
   *  backend. */
  venue_locality: string | null
  /** Display name of the Gathering's host (User who created the row). */
  host_name: string | null
  /** Public recording URL — surfaces the "Watch replay" CTA on
   *  archive cards. Detail responses also expose it. */
  recording_url: string | null
  /** Standalone paid Gatherings — null unless the access type is
   *  `paid_separately` AND the caretaker has set a price. */
  ticket_price_cents: number | null
  ticket_currency: string | null
  /** Mirrors the platform's `standalone_gathering_sales_enabled` flag
   *  so the UI can render "Ticket sales aren't open yet" instead of a
   *  Buy button that would immediately 503. */
  sales_enabled: boolean
}

export interface EventDetail extends EventSummary {
  location_url: string | null
  // recording_url inherited from EventSummary
  /** Full venue address + arrival instructions — the server scrubs
   *  these for non-attendees, so treat null as "not permitted to
   *  see" rather than "not set". */
  venue_address: string | null
  access_instructions: string | null
  // thumbnail_url and status inherited from EventSummary
}

export interface SeriesBookingResult {
  booked: number
  already_booked: number
  skipped_full: number
  skipped_closed: number
  total_in_series: number
}

export interface EventBooking {
  booking_id: string
  user_id: string
  name: string | null
  email: string
  booked_at: string
  status: 'confirmed' | 'cancelled' | 'pending_payment'
  source: string | null
  note: string | null
  attendance_status: 'pending' | 'attended' | 'no_show' | null
  attendance_marked_at: string | null
  /** Stage 3: DB-authoritative access-source label — Paid ticket,
   * Complimentary, Creator added, Included, Cancelled, Payment pending. */
  access_source: string
  /** Present only when a linked PaymentTransaction is 'succeeded'. */
  amount_paid_cents: number | null
  currency: string | null
  purchased_at: string | null
}

export interface CreatorMemberDetail {
  id: string
  display_name: string
  email: string
  space_role: 'learner' | 'moderator' | 'creator'
  joined_at: string
  is_creator: boolean
}

export interface MemberBookingItem {
  booking_id: string
  event_id: string
  event_title: string
  event_starts_at: string
  event_location_type: string
  booking_status: 'confirmed' | 'cancelled'
  attendance_status: 'pending' | 'attended' | 'no_show' | null
  booked_at: string
}

export interface AddMemberResponse {
  result: 'added_as_member' | 'pending_invite_created' | 'invite_created' | 'already_member' | 'invite_already_pending'
  message: string
}

export interface MemberProfile {
  id: string
  display_name: string
  avatar_url: string | null
  space_role: 'learner' | 'moderator' | 'creator'
  joined_at: string
  bio: string | null
  profile_tagline: string | null
  is_creator: boolean
}

export interface MemberPathwayAccessItem {
  id: string
  slug: string
  title: string
  pathway_status: string
  access_type: string
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
  access_state: string           // accessible | locked | coming_soon | draft | archived
  access_label: string           // Free | Included | Purchased | Subscribed | Locked | Coming soon | Draft
  access_source: string | null
  total_steps: number
  completed_steps: number
  progress_pct: number
  last_activity_at: string | null
  enrollment_status: string | null
}

export interface PublicProfile {
  id: string
  display_name: string
  avatar_url: string | null
  bio: string | null
  profile_tagline: string | null
  is_creator: boolean
  joined_platform: string
  spaces_led: string[]
}

export interface PostAuthor {
  id: string
  name: string | null
  email: string
  display_name: string
}

export interface ReactionCount {
  emoji: string
  count: number
  reacted: boolean
}

export interface CommentItem {
  id: string
  body: string
  image_url: string | null
  author: PostAuthor
  created_at: string
  reactions: ReactionCount[]
  // Community Phase 1
  parent_comment_id?: string | null
  parent_author_name?: string | null
  mentioned_user_ids?: string[]
}

/** Community Phase 1 — poll payload attached to a post. Result-visibility
 *  fields are resolved server-side; the client just renders what it's told. */
export interface PollViewData {
  allow_multiple: boolean
  is_anonymous: boolean
  show_results_before_vote: boolean
  closes_at: string | null
  total_voters: number
  user_has_voted: boolean
  can_edit: boolean
  is_closed: boolean
  show_results: boolean
  options: {
    id: string
    label: string
    position: number
    vote_count: number
    voted: boolean
  }[]
}

export interface StepComment {
  id: string
  body: string
  author: PostAuthor
  created_at: string
}

export type PostTypeValue =
  | 'reflection' | 'question' | 'poll' | 'announcement' | 'celebration' | 'share'
  // Legacy values are still round-tripped by the API.
  | 'prompt' | 'discussion'

export interface PostSummary {
  id: string
  post_type: PostTypeValue
  title: string | null
  body: string
  image_url: string | null
  is_pinned: boolean
  author: PostAuthor
  comment_count: number
  created_at: string
  reactions: ReactionCount[]
  // Community Phase 1
  mentioned_user_ids?: string[]
  poll?: PollViewData | null
}

export interface PostDetail extends Omit<PostSummary, 'comment_count'> {
  comments: CommentItem[]
}

export interface ManualMember {
  id: string
  first_name: string
  last_name: string | null
  display_name: string
  email: string | null
  phone: string | null
  notes: string | null
  pass_label: string | null
  payment_option_id: string | null
  payment_option_name: string | null
  payment_status: 'unpaid' | 'pending' | 'paid' | 'complimentary'
  status: 'offline' | 'managed' | 'invited' | 'converted'
  created_at: string
  updated_at: string
}

export interface ManualMemberPathwayAccess {
  pathway_id: string
  pathway_title: string
  pathway_slug: string
  grant_id: string
  granted_at: string
  notes: string | null
}

export interface DirectMessageItem {
  id: string
  sender_id: string
  sender_name: string
  body: string
  is_read: boolean
  created_at: string
}

export interface MessageThreadSummary {
  thread_id: string
  other_user_id: string
  other_user_name: string
  last_message: string | null
  last_message_at: string | null
  unread_count: number
}

export interface MessageThreadDetail {
  thread_id: string
  space_id: string
  creator_id: string
  creator_name: string
  member_id: string
  member_name: string
  messages: DirectMessageItem[]
  unread_count: number
}

export interface PathwayUnlockOption {
  id: string
  name: string
  payment_type: string
}

export interface UserProfile {
  id: string
  email: string
  name: string | null
  role: string
  bio: string | null
  display_name: string | null
  profile_tagline: string | null
  avatar_url: string | null
  is_public: boolean
  has_completed_onboarding: boolean
  has_completed_creator_onboarding: boolean
  interests: string[]
  // SEC-009 — null = unverified. Frontend surfaces a verification
  // banner + resend action when this is null.
  email_verified_at: string | null
}

export interface NotificationPrefs {
  space_id: string
  space_slug: string
  space_name: string
  weekly_digest_email: boolean
  daily_digest_email: boolean
  admin_broadcast_email: boolean
  gathering_reminder_email: boolean
  new_post_email: boolean
  comment_reply_email: boolean
  pathway_comment_email: boolean
  new_pathway_email: boolean
  push_enabled: boolean
  push_gathering_reminders: boolean
  push_replies: boolean
  push_announcements: boolean
}

export interface NotificationItem {
  id: string
  notification_type: string
  title: string
  message: string
  url: string | null
  is_read: boolean
  created_at: string
  read_at: string | null
}

export interface NotificationsResponse {
  notifications: NotificationItem[]
  unread_count: number
}

export interface SpaceMembership {
  space_id: string
  space_name: string
  space_slug: string
  role: 'learner' | 'moderator' | 'creator'
  joined_at: string
  status: string
}

// ---------------------------------------------------------------------------
// Creator Studio
// ---------------------------------------------------------------------------

export interface GuidancePanel {
  guidance_start_title: string | null
  guidance_start_body: string | null
  guidance_focus_title: string | null
  guidance_focus_body: string | null
  guidance_links_title: string | null
  guidance_links_body: string | null
}

export interface CreatorSpaceDetail extends GuidancePanel {
  id: string
  slug: string
  name: string
  tagline: string | null
  description: string | null
  about_content: string | null
  is_public: boolean
  /** See `SpaceResponse.auto_grant_role`. Locks Settings + hides join. */
  auto_grant_role?: string | null
  status: string
  timezone: string
  cover_image_url: string | null
  /** Optional "hosted by" mark shown subtly beside the collective name. */
  logo_url?: string | null
  themes: string[]
  pricing_type: PricingType
  pricing_amount_cents: number | null
  pricing_currency: string
  pricing_note: string | null
  has_paid_internal_content: boolean
  included_access_summary: string | null
  paid_content_summary: string | null
  derived_has_paid_internal_content: boolean
  // Atlas v1.2 identity fields — hydrated by the creator space detail response.
  location_id?: string | null
  location?: {
    id: string
    key: string
    name: string
    description: string | null
    hero_artwork_url: string | null
    thumbnail_artwork_url: string | null
    /** Long-form Atlas Entry from World Management — read-only in
     *  Creator Studio; helps the Creator understand the feeling and
     *  story of the chosen island. Editing lives in /admin/atlas. */
    atlas_entry?: string | null
  } | null
  colour_palette_key?: string | null
  colour_palette?: {
    key: string
    name: string
    palette: { primary: string; secondary: string; accent: string; background: string }
  } | null
  atmosphere_keys?: string[]
  atmosphere_labels?: string[]
  identity_statement?: string | null
  welcome_message?: string | null
  // Place & Feel — Discovery pillar. connection_style is set by
  // the Creator through Place & Feel; primary_place is the resolved
  // Geographic Location (null when connection_style is 'online').
  connection_style?: 'online' | 'in_person' | 'both'
  primary_place?: {
    id: string
    slug: string
    name: string
    region: string | null
    country_code: string
  } | null
}

/** How members experience a pathway. Guided Experience is the
 *  original per-step flow; Knowledge Guide renders the whole pathway
 *  as one continuous reference document. Same content model either
 *  way — the type only affects the member surface. */
export type PathwayType = 'guided_experience' | 'knowledge_guide'

export interface CreatorPathway {
  id: string
  slug: string
  title: string
  description: string | null
  practice_body: string | null
  cover_image_url: string | null
  status: 'draft' | 'active' | 'coming_soon' | 'archived'
  access_type: 'free' | 'included' | 'one_time' | 'subscription' | 'included_with_offer'
  pricing_mode: 'legacy' | 'payment_options'
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
  is_sequential: boolean
  pathway_type: PathwayType
  position: number
  step_count: number
  updated_at: string | null
  created_at: string
}

export interface CreatorStep {
  id: string
  slug: string
  title: string
  content_type: 'text' | 'video' | 'reflection' | 'exercise' | 'audio'
  content_body: string | null
  content_url: string | null
  estimated_minutes: number | null
  is_required: boolean
  position: number
  section_position: number | null
  section_id: string | null
  reflection_enabled: boolean
  discussion_enabled: boolean
  banner_image_url?: string | null
  // Drip scheduling — populated by the creator step endpoint.
  release_type?: ReleaseType
  release_offset_days?: number | null
  release_at?: string | null
  release_timezone?: string | null
  release_previous_state?: 'completed' | 'started'
}

export interface CreatorEvent {
  id: string
  title: string
  description: string | null
  starts_at: string
  ends_at: string | null
  location_type: 'zoom' | 'in_person' | 'async_recorded'
  location_url: string | null
  recording_url: string | null
  is_published: boolean
  is_public: boolean
  requires_booking: boolean
  capacity: number | null
  booking_closes_at: string | null
  booking_note: string | null
  booked_count: number
  attended_count: number
  no_show_count: number
  thumbnail_url: string | null
  status: 'active' | 'cancelled' | 'archived'
  recurrence_series_id: string | null
  recurrence_label: string | null
  recurrence_index: number | null
  recurrence_total: number | null
  /** Semantic Gathering Series membership (migration 105).
   *  Distinct from ``recurrence_series_id`` above: a bulk-created
   *  batch may set both; a hand-created event can be attached to a
   *  Series independently. */
  series_id: string | null
  created_at: string
  /** Gatherings 2.0 vocabulary — see `lib/gatheringTypes.ts`. */
  gathering_type: string
  attendance_format: 'online' | 'in_person' | 'hybrid'
  venue_name: string | null
  venue_address: string | null
  access_instructions: string | null
  booking_access_type: string
  booking_required_pathway_id: string | null
  /** Standalone paid Gatherings — nullable except on published paid events. */
  ticket_price_cents: number | null
  ticket_currency: string | null
  /** Creator-facing sales aggregate; null for non-paid Gatherings. */
  ticket_sales: TicketSalesSummary | null
}

export interface TicketSalesSummary {
  status: 'open' | 'sold_out' | 'closed' | 'cancelled' | 'ended' | 'not_paid'
  paid_ticket_count: number
  complimentary_count: number
  confirmed_booking_count: number
  active_hold_count: number
  remaining_capacity: number | null
  gross_ticket_revenue_cents: number
  revenue_currency: string | null
  has_completed_ticket_sales: boolean
  has_active_payment_holds: boolean
  sales_enabled: boolean
  stripe_mode: 'test' | 'live'
}

export interface CreatorPost {
  id: string
  post_type: string
  title: string | null
  body: string
  image_url: string | null
  is_pinned: boolean
  is_visible: boolean
  created_at: string
  author_name: string
}

export type MediaAssetType = 'image' | 'video' | 'audio' | 'document' | 'other'
export type MediaAssetStatus = 'active' | 'archived'

export interface CreatorMediaAsset {
  id: string
  space_id: string
  uploaded_by_user_id: string
  title: string
  description: string | null
  /** Optional alt text used when this asset is rendered (images, covers). */
  alt_text: string | null
  /** Comma-separated tag list (lightweight, no separate tag table). */
  tags: string | null
  original_filename: string
  stored_filename: string
  storage_path: string
  file_url: string
  mime_type: string
  media_type: MediaAssetType
  file_size_bytes: number
  extension: string
  status: MediaAssetStatus
  /** Unified Library folder — nullable ("All items"). */
  folder_id?: string | null
  /** Count of pathway-block references (read-only). */
  usage_count: number
  created_at: string
  updated_at: string
}

// ── Unified Library ─────────────────────────────────────────────────
//
// One creator surface over two backing stores. The creator never sees
// which store an item lives in — the frontend just reads
// ``LibraryItem`` from ``GET /api/creator/spaces/{slug}/library``.

/** Category the unified Library sorts items into. Maps loosely to
 *  MIME family for files; ``link`` is the SpaceResource kind. */
export type LibraryMediaType = 'image' | 'video' | 'audio' | 'document'

export interface LibraryFolder {
  id: string
  name: string
  position: number
  item_count: number
}

export interface LibraryFileInfo {
  url: string
  mime_type: string | null
  size_bytes: number | null
  original_filename: string | null
  media_type: LibraryMediaType
  extension: string | null
}

export interface LibraryLinkInfo {
  url: string
  resource_type: string
}

export interface LibraryItem {
  /** 'file' = ``CreatorMediaAsset``; 'link' = ``SpaceResource``.
   *  Implementation detail — used only to route mutations to the
   *  right endpoint. Not surfaced to the creator. */
  kind: 'file' | 'link'
  id: string
  title: string
  description: string | null
  folder_id: string | null
  used_in_count: number
  file: LibraryFileInfo | null
  link: LibraryLinkInfo | null
  created_at: string
  updated_at: string
}

export interface LibraryListResponse {
  items: LibraryItem[]
  total: number
  limit: number
  offset: number
  folders: LibraryFolder[]
}

export interface StepResource {
  id: string
  resource_type: 'video' | 'audio' | 'pdf' | 'file' | 'link'
  title: string
  description: string | null
  url: string | null
  file_name: string | null
  file_size: number | null
  mime_type: string | null
  position: number
  is_downloadable: boolean
  created_at: string
}

export type PricingType = 'free' | 'paid_one_time' | 'paid_monthly' | 'paid_annual' | 'invite_only' | 'coming_soon'

export type ResourceType = 'link' | 'file' | 'replay' | 'guide' | 'template' | 'audio' | 'video' | 'other'

export interface CollectiveResource {
  id: string
  title: string
  description: string | null
  resource_type: ResourceType
  url: string | null
  file_name: string | null
  file_size: number | null
  sort_order: number
  created_at: string
  scope?: 'general' | 'pathway'
  pathway_id?: string | null
  source?: string
}

export interface PathwayResourceItem {
  id: string
  title: string
  description: string | null
  resource_type: string
  url: string | null
  file_name: string | null
  file_size: number | null
  mime_type: string | null
  is_downloadable: boolean
  step_id: string | null
  step_title: string | null
  source: string
}

export interface PathwayResourceGroup {
  pathway_id: string
  pathway_title: string
  pathway_slug: string
  access_label: string
  resources: PathwayResourceItem[]
}

export interface AggregatedResourcesResponse {
  standalone_resources: CollectiveResource[]
  pathway_resource_groups: PathwayResourceGroup[]
}

export interface ResourcePathwayInfo {
  id: string
  slug: string
  title: string
}

export interface CreatorResource extends CollectiveResource {
  /** v2 status — includes 'archived' */
  status: 'draft' | 'published' | 'archived'
  /** v2 many-to-many. Empty array = General. */
  pathways: ResourcePathwayInfo[]
  /** Count of pathway-block references (read-only) */
  usage_count: number
  /** Legacy back-compat fields — still populated, but new UI uses `pathways`. */
  scope: 'general' | 'pathway'
  pathway_id: string | null
  updated_at: string
}

export interface ResourceUsageReference {
  kind: 'step_block' | 'about_block'
  pathway_id: string | null
  pathway_title: string | null
  pathway_slug: string | null
  step_id: string | null
  step_title: string | null
  step_slug: string | null
  href: string | null
}

export interface ResourceUsageResponse {
  resource_id: string
  references: ResourceUsageReference[]
}

export interface MediaUsageReference {
  kind: string
  pathway_id: string | null
  pathway_title: string | null
  pathway_slug: string | null
  step_id: string | null
  step_title: string | null
  step_slug: string | null
  label: string | null
}

export interface MediaUsageResponse {
  media_id: string
  references: MediaUsageReference[]
}

export interface PublicSpaceCard {
  id: string
  slug: string
  name: string
  tagline: string | null
  description: string | null
  cover_image_url: string | null
  is_public: boolean
  pathway_count: number
  member_count: number
  creator_name: string | null
  has_upcoming_event: boolean
  themes: string[]
  pricing_type: PricingType
  pricing_amount_cents: number | null
  pricing_currency: string
  pricing_note: string | null
  has_paid_internal_content: boolean
  included_access_summary: string | null
  paid_content_summary: string | null
  derived_has_paid_internal_content: boolean
  /** Atlas v1.2 — the collective's assigned Location artwork. Prefer the
   *  thumbnail for card displays, hero for large previews, and fall back
   *  to `cover_image_url` for legacy spaces with no Location assigned. */
  location_hero_artwork_url?: string | null
  location_thumbnail_artwork_url?: string | null
  min_paid_pathway_price_cents: number | null
}

export interface SpaceInvitation {
  id: string
  space_id: string
  email: string
  name: string | null
  role: 'learner' | 'moderator' | 'creator'
  note: string | null
  invited_by_id: string
  token: string
  payment_option_id: string | null
  payment_option_name: string | null
  payment_status: string
  sent_at: string | null
  created_at: string
}

export interface SpaceAccessStatus {
  is_member: boolean
  membership_role: 'learner' | 'moderator' | 'creator' | null
  has_pending_request: boolean
  has_pending_invite: boolean
}

export interface AccessRequest {
  id: string
  space_id: string
  user_id: string
  user_display_name: string
  user_email: string
  status: 'pending' | 'approved' | 'declined'
  message: string | null
  created_at: string
}

export interface InviteLookupResponse {
  id: string
  space_id: string
  space_name: string
  space_slug: string
  email: string
  name: string | null
  role: 'learner' | 'moderator' | 'creator'
}

export interface ContinueResponse {
  space_slug: string
  pathway_slug: string
  pathway_title: string
  step_slug: string
  step_title: string
  all_complete: boolean
}

export type StepBlockType =
  | 'heading'
  | 'text'
  | 'image'
  | 'video_embed'
  | 'audio'
  | 'file_download'
  | 'link'
  | 'reflection_prompt'
  | 'exercise'
  | 'callout'
  | 'divider'
  | 'embed'
  | 'button'
  | 'resource'
  | 'columns'

export interface StepBlockMedia {
  id: string
  title: string
  file_url: string
  media_type: MediaAssetType
  mime_type: string
  original_filename: string
}

/** Live snapshot of the linked SpaceResource included in step/about block responses. */
export interface StepBlockResource {
  id: string
  title: string
  description: string | null
  resource_type: ResourceType
  url: string | null
  file_name: string | null
  status: 'draft' | 'published'
  scope: 'general' | 'pathway'
}

export interface StepBlock {
  id: string
  step_id: string
  block_type: StepBlockType
  position: number
  content: string | null
  label: string | null
  caption: string | null
  embed_url: string | null
  media_asset_id: string | null
  media_asset: StepBlockMedia | null
  resource_id: string | null
  resource: StepBlockResource | null
  container_style: string | null
  created_at: string
  updated_at: string
}

export interface PathwayAboutBlock {
  id: string
  pathway_id: string
  block_type: StepBlockType
  position: number
  content: string | null
  label: string | null
  caption: string | null
  embed_url: string | null
  media_asset_id: string | null
  media_asset: StepBlockMedia | null
  resource_id: string | null
  resource: StepBlockResource | null
  container_style: string | null
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Creator Billing
// ---------------------------------------------------------------------------

export interface CreatorPlanOut {
  // Identity + pricing
  id: string
  name: string
  slug: string
  description: string | null
  /** Null for Organisation ("Talk to us"). Every other plan has a price. */
  monthly_price_cents: number | null
  currency: string

  // Legacy DB-backed limit fields (kept for admin plan-editor UI and
  // backwards compatibility; the canonical values live in the capability
  // fields below).
  transaction_fee_basis_points: number | null
  collective_limit: number | null
  pathway_limit: number | null
  media_storage_limit_mb: number | null
  creator_admin_seat_limit: number | null

  // Canonical capability record (mirrors backend/app/creator/plan_config.py).
  // Numeric fields left as `null` mean "to be defined in creator plan design"
  // — render "To be defined" in the UI, never guess a value.
  tagline: string
  positioning: string

  active_collective_limit: number | null
  member_allowance_per_collective: number | null
  pooled_member_allowance: number | null
  caretaker_limit_per_collective: number | null
  storage_allowance_mb: number | null

  /** 'atlas_subset' | 'atlas_full' | 'atlas_and_cornerstones' */
  location_scope: string
  /** 'basic' | 'standard' | 'advanced' */
  analytics_level: string

  paid_offers_enabled: boolean
  pathways_enabled: boolean
  gatherings_enabled: boolean
  resources_enabled: boolean
  automations_enabled: boolean
  commercial_use: boolean
  approval_required: boolean
  /** False for Organisation — no self-service subscription. */
  is_self_service: boolean
  /** False for Organisation — no self-service checkout. */
  is_purchasable: boolean

  card_headline: string
  card_features: string[]
}

export interface CreatorSubscriptionOut {
  id: string
  status: 'active' | 'trialing' | 'past_due' | 'cancelled' | 'unpaid'
  starts_at: string
  ends_at: string | null
  stripe_connected: boolean
}

export interface CreatorUsage {
  collectives_used: number
  pathways_used: number
  media_storage_used_mb: number | null
}

export interface CreatorPaymentSetup {
  creator_billing_connected: boolean
  member_payments_connected: boolean  // True when FC platform Stripe is configured for member checkout
  stripe_connect_connected: boolean   // True when creator's own Stripe Connect account is active (Phase 2+)
  stripe_test_mode: boolean           // True when platform is using Stripe test keys
}

export interface CreatorBillingResponse {
  /** Present only for Creator accounts (Free / Plus / Pro). Null when the
   *  authenticated user is a Platform Owner — Platform Owners are their own
   *  account type and do not belong to any creator subscription plan. */
  current_plan: CreatorPlanOut | null
  /** Present only for Creator accounts. Null for Platform Owners. */
  subscription: CreatorSubscriptionOut | null
  usage: CreatorUsage
  /** Empty for Platform Owners; the plan lineup is meaningless for that account type. */
  available_plans: CreatorPlanOut[]
  payment_setup: CreatorPaymentSetup
  /** True when the user is the Fresh Collective Platform Owner. */
  is_platform_owner: boolean
}


// ---------------------------------------------------------------------------
// Offer Pages
//
// Presentation-layer entity: an Offer Page is a public sales page for
// an existing sellable (Pathway in V1). Commerce plumbing stays where
// it is — the CTA deep-links to the target's existing checkout.
// ---------------------------------------------------------------------------

export type OfferPageStatus = 'draft' | 'published' | 'archived'
/** What an Offer Page invites people into. Values are the wire
 *  contract with the backend; the UI never surfaces `event_series`
 *  as a string — creator-facing labels are always
 *  "Pathway" | "Gathering Series" | "Gathering". */
export type OfferPageTargetKind = 'pathway' | 'event_series' | 'gathering'

/** Restrained TipTap JSON. The Invitation editor exposes a small
 *  set of marks (bold, italic, links) + paragraphs + a single
 *  heading level; content is stored as a JSON string. */
export type OfferInvitationBody = string

export interface OfferInvitationSection {
  enabled: boolean
  body: string | null
}

export interface OfferWhatsIncludedSection {
  enabled: boolean
  items: string[]
}

export interface OfferPracticalSection {
  enabled: boolean
  dates: string | null
  duration: string | null
  location: string | null
  format: string | null
  access_period: string | null
  capacity: string | null
  requirements: string | null
}

export interface OfferFaqItem {
  question: string
  answer: string
}

export interface OfferFaqsSection {
  enabled: boolean
  items: OfferFaqItem[]
}

export interface OfferCreatorSection {
  enabled: boolean
}

/** The typed sections shape the editor writes. The backend stores it
 *  as a JSON blob and returns the raw dict on reads — the frontend
 *  narrows via ``normaliseSectionsConfig`` at the editor boundary
 *  so shape evolution never crashes a page. */
export interface OfferSectionsConfig {
  invitation: OfferInvitationSection
  whats_included: OfferWhatsIncludedSection
  practical: OfferPracticalSection
  faqs: OfferFaqsSection
  creator: OfferCreatorSection
}

/** Full editor payload. */
export interface CreatorOfferPage {
  id: string
  space_id: string
  slug: string
  title: string
  promise: string | null
  hero_image_url: string | null
  target_kind: OfferPageTargetKind
  target_id: string
  status: OfferPageStatus
  sections_config: Partial<OfferSectionsConfig> & Record<string, unknown>
  published_at: string | null
  /** Derived on the backend: permanent once ``published_at`` is set. */
  slug_locked: boolean
  created_at: string
  updated_at: string
}

/** Published PaymentOptionSchedule surfaced on the public Offer Page
 *  for a Gathering Series target. */
export interface PublicPaymentOptionSchedule {
  id: string
  name: string
  description: string | null
  schedule_type: string
  total_amount_cents: number | null
  upfront_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  buyer_note: string | null
  /** Backend-authoritative — see
   *  ``PaymentOptionScheduleSummary.is_member_checkoutable``. */
  is_member_checkoutable: boolean
}

/** Published PaymentOption + its published schedules — surfaced on
 *  the public Offer Page for a Gathering Series target. */
export interface PublicPaymentOption {
  id: string
  name: string
  description: string | null
  payment_type: string
  sessions_per_week: number | null
  total_sessions: number | null
  price_per_session_cents: number | null
  effective_price_cents: number | null
  currency: string
  buyer_note: string | null
  schedules: PublicPaymentOptionSchedule[]
}

/** Real Creator identity behind the Space. `null` on `PublicOfferPage`
 *  when no personal Creator info exists — never falls back to the
 *  Collective name. */
export interface PublicOfferCreator {
  display_name: string | null
  tagline: string | null
  bio: string | null
  avatar_url: string | null
  website_url: string | null
}

/** Denormalised target snapshot returned by the public Offer Page read.
 *  Everything the CTA needs to route + label without a second fetch. */
export interface OfferPageTargetSnapshot {
  kind: OfferPageTargetKind
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  access_type: string | null
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
  checkout_path: string | null
  enter_path: string | null
  /** Series/gathering window; null for `pathway`. */
  starts_at: string | null
  ends_at: string | null
  /** Series-only: published Payment Options + Schedules. */
  payment_options: PublicPaymentOption[]
  /** Gathering-only: standalone ticket price. */
  ticket_price_cents: number | null
  ticket_currency: string | null
}

/** Public shape returned by GET /api/spaces/{slug}/offers/{offer_slug}.
 *  Only published pages are visible to non-owners; owners see drafts +
 *  archived through the same URL (no separate preview mode). */
export interface PublicOfferPage {
  id: string
  slug: string
  title: string
  promise: string | null
  hero_image_url: string | null
  status: OfferPageStatus
  sections_config: Partial<OfferSectionsConfig> & Record<string, unknown>
  target: OfferPageTargetSnapshot
  creator: PublicOfferCreator | null
  user_has_target_access: boolean
}

/** Index row — light shape for the Offer Pages list. */
export interface CreatorOfferPageSummary {
  id: string
  slug: string
  title: string
  hero_image_url: string | null
  target_kind: OfferPageTargetKind
  target_id: string
  /** Populated by the server; null if the target has been deleted. */
  target_title: string | null
  status: OfferPageStatus
  slug_locked: boolean
  updated_at: string
}

/** Minimal shared shape used by block editor sub-components. */
export interface EditorBlock {
  id: string
  block_type: StepBlockType
  position: number
  content: string | null
  label: string | null
  caption: string | null
  embed_url: string | null
  media_asset_id: string | null
  media_asset: StepBlockMedia | null
  resource_id: string | null
  resource: StepBlockResource | null
  container_style: string | null
}

// ---------------------------------------------------------------------------
// Access Passes (Phase B)
// ---------------------------------------------------------------------------

export interface AccessPassSummary {
  id: string
  pass_type: 'pathway_access' | 'term_pass' | 'class_pass' | 'event_ticket' | 'retreat_booking' | 'membership' | 'bundle'
  status: 'pending' | 'active' | 'used' | 'expired' | 'cancelled' | 'suspended'
  valid_from: string
  valid_until: string | null
  total_credits: number | null
  used_credits: number
  remaining_credits: number | null
  credits_per_week: number | null
  eligible_pathway_id: string | null
  eligible_series_id: string | null
  option_name: string | null
  pathway_title: string | null
  payment_option_id: string | null
  option_included_items: string[]
  access_source: string | null
  payment_transaction_id: string | null
  created_at: string
}

export interface AccessPassAdminSummary extends AccessPassSummary {
  user_id: string | null
  member_name: string | null
  member_email: string | null
  total_bookings: number
  recent_bookings: number
}


// ---------------------------------------------------------------------------
// Activity Engine — mirrors backend `ActivityOut` / `ActivityListResponse`.
// ---------------------------------------------------------------------------

export type ActivityCategory =
  | 'personal'
  | 'conversations'
  | 'gatherings'
  | 'pathways'
  | 'collective'
  | 'account'

export interface ActivityOut {
  id: string
  event_type: string
  category: ActivityCategory | string
  priority: string
  actor_user_id: string | null
  recipient_user_id: string
  collective_id: string | null
  pathway_id: string | null
  gathering_id: string | null
  conversation_id: string | null
  resource_id: string | null
  /** Writer-supplied. Callers read ``payload.title`` for the visible
   *  title and ``payload.url`` for the target URL. Missing fields
   *  degrade to a per-event-type fallback in the UI. */
  payload: { title?: string; url?: string; [k: string]: unknown }
  read_at: string | null
  archived_at: string | null
  created_at: string
}

export interface ActivityListResponse {
  activities: ActivityOut[]
  next_before: string | null
}

// ---------------------------------------------------------------------------
// Gathering Series (Step 2 — Creator UI)
// ---------------------------------------------------------------------------

export type GatheringSeriesStatus = 'draft' | 'published' | 'archived'

export interface CreatorGatheringSeriesSummary {
  id: string
  slug: string
  title: string
  starts_at: string
  ends_at: string | null
  status: GatheringSeriesStatus
  cover_image_url: string | null
  gathering_count: number
  payment_option_count: number
  updated_at: string
}

export interface CreatorGatheringSeries {
  id: string
  space_id: string
  slug: string
  title: string
  description: string | null
  starts_at: string
  ends_at: string | null
  status: GatheringSeriesStatus
  cover_image_url: string | null
  /** Set on first publish, never cleared. Frontend keys off this
   *  to decide whether Delete (never published) or Archive is the
   *  correct lifecycle action to expose. */
  published_at: string | null
  created_at: string
  updated_at: string
}

/** Ways to pay for a single Payment Option — same access
 *  entitlement, different Stripe cadence. Backend model:
 *  ``PaymentOptionSchedule``. Creator-facing labels are handled in
 *  the UI (schedule_type → "Pay in full" / "Weekly instalments"). */
export interface CreatorPaymentOptionSchedule {
  id: string
  payment_option_id: string
  name: string
  description: string | null
  schedule_type: 'pay_in_full' | 'recurring_installments' | 'manual'
  status: 'draft' | 'published' | 'archived'
  total_amount_cents: number | null
  upfront_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  stripe_interval: string | null
  stripe_interval_count: number | null
  currency: string
  buyer_note: string | null
  internal_note: string | null
  position: number
  created_at: string
  updated_at: string
}

/** Polymorphic attachment now exposed by the PaymentOption
 *  serialiser (post-migration-105). Frontend keys on
 *  ``attaches_to_kind`` to decide which authoring surface a row
 *  belongs to. */
export type PaymentOptionAttachesToKind = 'pathway' | 'event_series'

export interface CreatorSeriesPaymentOption {
  id: string
  space_id: string
  pathway_id: string | null
  attaches_to_kind: PaymentOptionAttachesToKind
  attaches_to_id: string
  grants_pathway_id: string | null
  name: string
  description: string | null
  payment_type: 'free' | 'one_time' | 'term_pass' | 'subscription'
  status: 'draft' | 'published' | 'archived'
  term_start_date: string | null
  term_end_date: string | null
  sessions_per_week: number | null
  total_sessions: number | null
  price_per_session_cents: number | null
  calculated_total_cents: number | null
  override_total_cents: number | null
  effective_price_cents: number | null
  currency: string
  buyer_note: string | null
  internal_note: string | null
  position: number
  created_at: string
  updated_at: string
}
