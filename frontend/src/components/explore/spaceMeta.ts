import type { PublicSpaceCard } from '@/types/platform'

export interface SpaceWithMeta extends PublicSpaceCard {
  category: string
  accentColor: string
  isReal: boolean
}

// TODO: Connect collectives to category taxonomy once category data is finalised.
export const SPACE_META: Record<
  string,
  Pick<SpaceWithMeta, 'category' | 'accentColor'>
> = {
  'fresh-collective': { category: 'Inner Work', accentColor: '#38A09E' },
}

export function toSpaceWithMeta(card: PublicSpaceCard): SpaceWithMeta {
  const meta = SPACE_META[card.slug] ?? {
    category: 'Inner Work',
    accentColor: '#38A09E',
  }
  return { ...card, ...meta, isReal: true }
}
