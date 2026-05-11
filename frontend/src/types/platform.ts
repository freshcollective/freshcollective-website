export interface PathwaySummary {
  id: string
  slug: string
  title: string
  description: string | null
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
