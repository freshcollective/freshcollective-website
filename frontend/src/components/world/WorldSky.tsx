import { COLLECTIVES, isMemberOf } from '@/lib/world/collectives'
import { generateBackdropStars } from '@/lib/world/starfield'
import ConstellationCluster from './ConstellationCluster'
import UserStar from './UserStar'

interface Props {
  memberSlugs: ReadonlyArray<string>
}

/**
 * The shared Fresh Collective sky. Deep ink navy — the mood is night, not
 * dashboard. Accent colour only appears as small, contained halos around
 * the constellation stars themselves, not as a wash across the sky.
 *
 * Every constellation is visible to every member; belonging is expressed
 * through a slightly brighter core, not through hiding what others hold.
 */
export default function WorldSky({ memberSlugs }: Props) {
  const stars = generateBackdropStars(1618, 180)

  return (
    <section
      aria-label="The Fresh Collective sky"
      className="relative w-full overflow-hidden"
      style={{
        aspectRatio: '16 / 8',
        // Deep ink navy — no teal wash. The one very subtle radial is a
        // "moon-adjacent glow" at upper right, in warm cream (barely
        // present).
        background:
          'radial-gradient(38% 30% at 82% 20%, rgba(247,239,199,0.06), transparent 70%),' +
          'radial-gradient(60% 45% at 50% 100%, rgba(6,20,36,0.55), transparent 70%),' +
          'linear-gradient(180deg, #02060D 0%, #050A18 45%, #060F1F 100%)',
      }}
    >
      {/* Backdrop starfield */}
      <svg
        viewBox="0 0 1000 500"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
        aria-hidden="true"
      >
        {stars.map((s, i) => (
          <circle
            key={i}
            cx={s.x * 1000}
            cy={s.y * 500}
            r={s.r}
            fill="#FAFAF8"
            opacity={s.o}
            className="world-twinkle"
            style={{ animationDelay: `${s.d.toFixed(2)}s` }}
          />
        ))}
      </svg>

      {/* Constellations */}
      <div className="absolute inset-0">
        {COLLECTIVES.map((c) => (
          <ConstellationCluster
            key={c.id}
            def={c}
            isMember={isMemberOf(c, memberSlugs)}
          />
        ))}
      </div>

      {/* Member's own star */}
      <UserStar />

      {/* Bottom fade — softens the transition into the page below */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-28"
        style={{
          background:
            'linear-gradient(180deg, transparent 0%, #030814 100%)',
        }}
        aria-hidden="true"
      />
    </section>
  )
}
