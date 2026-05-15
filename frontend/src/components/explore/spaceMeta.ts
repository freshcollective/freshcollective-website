import type { PublicSpaceCard } from '@/types/platform'

export interface SpaceWithMeta extends PublicSpaceCard {
  category: string
  accentColor: string
  isFlagship: boolean
  isReal: boolean
}

// TODO: Connect collectives to category taxonomy once category data is finalised.
export const SPACE_META: Record<
  string,
  Pick<SpaceWithMeta, 'category' | 'accentColor' | 'isFlagship'>
> = {
  'fresh-collective': { category: 'Inner Work', accentColor: '#38A09E', isFlagship: true },
}

export function toSpaceWithMeta(card: PublicSpaceCard): SpaceWithMeta {
  const meta = SPACE_META[card.slug] ?? {
    category: 'Inner Work',
    accentColor: '#38A09E',
    isFlagship: false,
  }
  return { ...card, ...meta, isReal: true }
}
