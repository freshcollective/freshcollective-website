import type { PublicSpaceCard } from '@/types/platform'

export interface SpaceWithMeta extends PublicSpaceCard {
  accentColor: string
  isReal: boolean
}

// accentColor is display-only — not stored in the database.
const SPACE_ACCENT: Record<string, string> = {
  'the-natural-leader-hub': '#38A09E',
  'embody': '#7E6E9A',
}

const DEFAULT_ACCENT = '#38A09E'

export function toSpaceWithMeta(card: PublicSpaceCard): SpaceWithMeta {
  return {
    ...card,
    accentColor: SPACE_ACCENT[card.slug] ?? DEFAULT_ACCENT,
    isReal: true,
  }
}
