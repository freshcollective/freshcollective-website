export interface PathwaySummary {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  status: 'draft' | 'active' | 'coming_soon' | 'archived'
  position: number
}

export interface SpaceResponse {
  id: string
  slug: string
  name: string
  tagline: string | null
  description: string | null
  is_public: boolean
  status: string
  pathways: PathwaySummary[]
}

export interface SpaceSummary {
  id: string
  slug: string
  name: string
  tagline: string | null
  status: string
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

export interface PathwayWithSteps {
  id: string
  slug: string
  title: string
  description: string | null
  status: string
  step_count: number
  completed_count: number
  steps: StepSummary[]
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
}

export interface EventSummary {
  id: string
  title: string
  description: string | null
  starts_at: string
  ends_at: string | null
  location_type: 'zoom' | 'in_person' | 'async_recorded'
}

export interface EventDetail extends EventSummary {
  location_url: string | null
  recording_url: string | null
}

export interface ContinueResponse {
  space_slug: string
  pathway_slug: string
  pathway_title: string
  step_slug: string
  step_title: string
  all_complete: boolean
}
