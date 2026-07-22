import PersonalIsland from './PersonalIsland'
import type { WorldElementType } from '@/lib/world/collectives'

interface Props {
  elements: ReadonlyArray<WorldElementType>
}

/**
 * Section wrapper for the personal-world preview. Full-bleed and edgeless:
 * the island lives inside the page atmosphere, not inside a card. The
 * PersonalIsland SVG already feathers its own top and bottom edges, so no
 * border or shadow is needed here.
 */
export default function MyWorldPreview({ elements }: Props) {
  return (
    <div
      className="relative w-full"
      style={{ aspectRatio: '16 / 6.4' }}
    >
      <PersonalIsland elements={elements} />
    </div>
  )
}
