import Link from 'next/link'
import type { ConstellationDef } from '@/lib/world/collectives'

interface Props {
  def: ConstellationDef
  /** True when the current member belongs to this collective. */
  isMember: boolean
}

/**
 * One collective constellation, absolutely positioned within the sky
 * container. Its bounding box (derived from the point coordinates) becomes
 * the click target and label anchor.
 *
 * When `def.href` is null, the collective is "forming" — the constellation
 * still appears in the sky (dimmer, no click target) with a quiet
 * "forming" mark instead of a name. The sky is allowed to describe
 * territory that is still being made.
 */
export default function ConstellationCluster({ def, isMember }: Props) {
  const xs = def.points.map((p) => p.x)
  const ys = def.points.map((p) => p.y)
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const maxX = Math.max(...xs)
  const maxY = Math.max(...ys)

  const PADDING = 0.02
  const boxLeft = minX - PADDING
  const boxTop = minY - PADDING
  const boxW = (maxX - minX) + 2 * PADDING
  const boxH = (maxY - minY) + 2 * PADDING

  const S = 1000
  const localX = (p: number) => ((p - minX + PADDING) / boxW) * S
  const localY = (p: number) => ((p - minY + PADDING) / boxH) * S

  const forming = def.href === null
  const baseOpacity = forming ? 0.42 : isMember ? 1 : 0.78

  const inner = (
    <>
      <svg
        viewBox={`0 0 ${S} ${S}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full transition-opacity duration-700 group-hover:opacity-100 group-focus-visible:opacity-100"
        style={{ opacity: baseOpacity }}
        aria-hidden="true"
      >
        {/* Connective lines */}
        <g>
          {def.lines.map(([a, b], i) => (
            <line
              key={i}
              x1={localX(def.points[a].x)}
              y1={localY(def.points[a].y)}
              x2={localX(def.points[b].x)}
              y2={localY(def.points[b].y)}
              stroke={def.accent}
              strokeWidth={2.2}
              strokeOpacity={forming ? 0.18 : 0.32}
              strokeLinecap="round"
            />
          ))}
        </g>

        {/* Halo behind each star */}
        <g>
          {def.points.map((p, i) => (
            <circle
              key={`halo-${i}`}
              cx={localX(p.x)}
              cy={localY(p.y)}
              r={28}
              fill={def.accent}
              opacity={forming ? 0.08 : 0.14}
              className="world-shimmer"
              style={{ animationDelay: `${(i * 0.55).toFixed(2)}s`, transformOrigin: 'center' }}
            />
          ))}
        </g>

        {/* Star cores */}
        <g>
          {def.points.map((p, i) => (
            <circle
              key={`core-${i}`}
              cx={localX(p.x)}
              cy={localY(p.y)}
              r={forming ? 5.5 : 7}
              fill="#FAFAF8"
              className="world-twinkle"
              style={{ animationDelay: `${(i * 0.4).toFixed(2)}s` }}
            />
          ))}
        </g>
      </svg>

      {/* Label */}
      <div
        className="pointer-events-none absolute left-1/2 -translate-x-1/2 whitespace-nowrap text-center"
        style={{ top: 'calc(100% + 6px)' }}
      >
        <p
          className="text-[10.5px] font-semibold uppercase tracking-[0.22em] transition-opacity duration-500"
          style={{
            color: def.accent,
            opacity: forming ? 0.55 : 0.9,
            textShadow: `0 0 14px ${def.glow}`,
          }}
        >
          {def.name}
        </p>
        {forming && (
          <p
            className="mt-1 text-[9.5px] uppercase tracking-[0.30em]"
            style={{ color: 'rgba(247, 239, 199, 0.55)' }}
          >
            Forming
          </p>
        )}
      </div>
    </>
  )

  return (
    <div
      className="absolute"
      style={{
        left: `${boxLeft * 100}%`,
        top: `${boxTop * 100}%`,
        width: `${boxW * 100}%`,
        height: `${boxH * 100}%`,
      }}
    >
      {def.href ? (
        <Link
          href={def.href}
          aria-label={`${def.name} — ${def.tagline}`}
          className="group relative block h-full w-full rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-white/40"
        >
          {inner}
        </Link>
      ) : (
        <div
          aria-label={`${def.name} — forming`}
          className="group relative h-full w-full"
        >
          {inner}
        </div>
      )}
    </div>
  )
}
