export interface PathwaySummary {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  status: 'draft' | 'active' | 'coming_soon' | 'archived'
  position: number
  access_type: 'free' | 'included' | 'one_time' | 'subscription'
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
  user_has_access: boolean
  step_count: number
}

export interface SpaceResponse {
  id: string
  slug: string
  name: string
  tagline: string | null
  description: string | null
  about_content: string | null
  is_public: boolean
  status: string
  timezone: string
  cover_image_url: string | null
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
  learner_count: number
}

export interface SpaceSummary {
  id: string
  slug: string
  name: string
  tagline: string | null
  status: string
  is_public: boolean
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
}

export interface StepDetail extends StepSummary {
  content_body: string | null
  content_url: string | null
  reflection_text: string | null
}

export interface PathwaySection {
  id: string
  title: string
  position: number
  steps: StepSummary[]
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
  access_type: 'free' | 'included' | 'one_time' | 'subscription'
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
  user_has_access: boolean
  payment_options: PaymentOptionSummary[]
}

export interface CreatorSection {
  id: string
  pathway_id: string
  title: string
  position: number
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
  access_type: 'free' | 'included' | 'one_time' | 'subscription'
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
  my_booking_status: 'confirmed' | 'cancelled' | null
  can_book: boolean
  can_cancel_booking: boolean
  recurrence_series_id: string | null
  recurrence_label: string | null
  recurrence_index: number | null
  recurrence_total: number | null
  is_public: boolean
  thumbnail_url: string | null
  status: 'active' | 'cancelled' | 'archived'
  booking_access_type: 'all_members' | 'pathway_required'
  booking_required_pathway_id: string | null
  user_has_pathway_access: boolean
}

export interface EventDetail extends EventSummary {
  location_url: string | null
  recording_url: string | null
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
  status: 'confirmed' | 'cancelled'
  source: string | null
  note: string | null
  attendance_status: 'pending' | 'attended' | 'no_show' | null
  attendance_marked_at: string | null
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
  result: 'added_as_member' | 'invite_created' | 'already_member' | 'invite_already_pending'
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

export interface CommentItem {
  id: string
  body: string
  author: PostAuthor
  created_at: string
}

export interface StepComment {
  id: string
  body: string
  author: PostAuthor
  created_at: string
}

export interface PostSummary {
  id: string
  post_type: 'prompt' | 'reflection' | 'discussion' | 'announcement'
  title: string | null
  body: string
  is_pinned: boolean
  author: PostAuthor
  comment_count: number
  created_at: string
}

export interface PostDetail extends Omit<PostSummary, 'comment_count'> {
  comments: CommentItem[]
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
  interests: string[]
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
  status: string
  timezone: string
  cover_image_url: string | null
  themes: string[]
  pricing_type: PricingType
  pricing_amount_cents: number | null
  pricing_currency: string
  pricing_note: string | null
  has_paid_internal_content: boolean
  included_access_summary: string | null
  paid_content_summary: string | null
  derived_has_paid_internal_content: boolean
}

export interface CreatorPathway {
  id: string
  slug: string
  title: string
  description: string | null
  practice_body: string | null
  cover_image_url: string | null
  status: 'draft' | 'active' | 'coming_soon' | 'archived'
  access_type: 'free' | 'included' | 'one_time' | 'subscription'
  price_cents: number | null
  currency: string | null
  billing_interval: string | null
  is_sequential: boolean
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
  created_at: string
}

export interface CreatorPost {
  id: string
  post_type: string
  title: string | null
  body: string
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
  original_filename: string
  stored_filename: string
  storage_path: string
  file_url: string
  mime_type: string
  media_type: MediaAssetType
  file_size_bytes: number
  extension: string
  status: MediaAssetStatus
  created_at: string
  updated_at: string
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

export interface CreatorResource extends CollectiveResource {
  status: 'draft' | 'published'
  scope: 'general' | 'pathway'
  pathway_id: string | null
  updated_at: string
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

export interface StepBlockMedia {
  id: string
  title: string
  file_url: string
  media_type: MediaAssetType
  mime_type: string
  original_filename: string
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
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Creator Billing
// ---------------------------------------------------------------------------

export interface CreatorPlanOut {
  id: string
  name: string
  slug: string
  description: string | null
  monthly_price_cents: number
  currency: string
  transaction_fee_basis_points: number
  collective_limit: number
  pathway_limit: number | null
  media_storage_limit_mb: number | null
  creator_admin_seat_limit: number | null
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
  current_plan: CreatorPlanOut
  subscription: CreatorSubscriptionOut
  usage: CreatorUsage
  available_plans: CreatorPlanOut[]
  payment_setup: CreatorPaymentSetup
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
}
