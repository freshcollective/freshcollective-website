import WorldElement from './WorldElement'
import type { WorldElementType } from '@/lib/world/collectives'
import { generateBackdropStars } from '@/lib/world/starfield'

interface Props {
  elements: ReadonlyArray<WorldElementType>
}

/**
 * The member's personal world — a small island under a night sky, seen
 * across a dark, still ocean. The scene is layered for depth:
 *
 *   1. Night sky (deep ink) with a scatter of soft stars
 *   2. Distant horizon glow — very faint
 *   3. Optional atmospheric elements behind the island (sunrise / mountain)
 *   4. Reflected starlight across the water
 *   5. The island itself (rock base → soft grass → shoreline)
 *   6. Ground-level elements (trees, garden, path, water, fire)
 *
 * All elements share the SVG coordinate space (0 0 1000 560).
 */
export default function PersonalIsland({ elements }: Props) {
  const has = (t: WorldElementType) => elements.includes(t)
  const stars = generateBackdropStars(271828, 60)
  const reflections = generateBackdropStars(31415, 22)

  return (
    <svg
      viewBox="0 0 1000 560"
      preserveAspectRatio="xMidYMid slice"
      className="h-full w-full"
      role="img"
      aria-label="Your personal world"
    >
      <defs>
        <linearGradient id="w-nightsky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor="#02060D" />
          <stop offset="55%"  stopColor="#050B18" />
          <stop offset="72%"  stopColor="#06121F" />
          <stop offset="100%" stopColor="#040915" />
        </linearGradient>

        <linearGradient id="w-water" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor="#050C1A" />
          <stop offset="40%"  stopColor="#071B27" />
          <stop offset="100%" stopColor="#040A14" />
        </linearGradient>

        <radialGradient id="w-horizonglow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%"   stopColor="#F7EFC7" stopOpacity="0.16" />
          <stop offset="55%"  stopColor="#BF9830" stopOpacity="0.05" />
          <stop offset="100%" stopColor="#BF9830" stopOpacity="0" />
        </radialGradient>

        <linearGradient id="w-rock" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor="#1A2733" />
          <stop offset="100%" stopColor="#0A1420" />
        </linearGradient>

        <linearGradient id="w-grass" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor="#204F44" />
          <stop offset="100%" stopColor="#0F2E28" />
        </linearGradient>

        <radialGradient id="w-islandglow" cx="0.5" cy="0.4" r="0.6">
          <stop offset="0%"   stopColor="#F7EFC7" stopOpacity="0.10" />
          <stop offset="100%" stopColor="#F7EFC7" stopOpacity="0" />
        </radialGradient>

        {/* Soft edge feather so the scene bleeds into the page */}
        <linearGradient id="w-edgetop" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#030814" stopOpacity="1" />
          <stop offset="100%" stopColor="#030814" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="w-edgebot" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#030814" stopOpacity="0" />
          <stop offset="100%" stopColor="#030814" stopOpacity="1" />
        </linearGradient>
      </defs>

      {/* Sky */}
      <rect x="0" y="0" width="1000" height="380" fill="url(#w-nightsky)" />

      {/* Stars in the sky */}
      <g>
        {stars.map((s, i) => (
          <circle
            key={`sky-${i}`}
            cx={s.x * 1000}
            cy={s.y * 300 + 20}
            r={s.r * 0.85}
            fill="#FAFAF8"
            opacity={s.o * 0.85}
            className="world-twinkle"
            style={{ animationDelay: `${s.d.toFixed(2)}s` }}
          />
        ))}
      </g>

      {/* Distant horizon glow — always present, very faint */}
      <ellipse cx="500" cy="380" rx="480" ry="70" fill="url(#w-horizonglow)" />

      {/* Layer 1 — atmospheric behind the island */}
      {has('sunrise')  && <WorldElement type="sunrise" />}
      {has('mountain') && <WorldElement type="mountain" />}

      {/* Water */}
      <rect x="0" y="360" width="1000" height="200" fill="url(#w-water)" />

      {/* Star reflections shimmering on water */}
      <g>
        {reflections.map((s, i) => (
          <ellipse
            key={`ref-${i}`}
            cx={s.x * 1000}
            cy={400 + s.y * 130}
            rx={s.r * 1.4}
            ry={s.r * 0.35}
            fill="#F7EFC7"
            opacity={s.o * 0.32}
            className="world-flow"
            style={{ animationDelay: `${(s.d * 1.5).toFixed(2)}s` }}
          />
        ))}
      </g>

      {/* Distant island silhouettes — depth */}
      <path
        d="M 60 388 C 130 378 190 384 250 388 C 300 391 350 386 400 390 L 400 400 L 60 400 Z"
        fill="#0A1524"
        opacity="0.7"
      />
      <path
        d="M 620 390 C 700 380 780 386 870 392 C 920 395 960 390 1000 390 L 1000 402 L 620 402 Z"
        fill="#0A1524"
        opacity="0.6"
      />

      {/* Island shadow on water */}
      <ellipse cx="500" cy="470" rx="260" ry="14" fill="rgba(0,0,0,0.55)" />

      {/* Island — rock base, organic silhouette, not a symmetric mound */}
      <path
        d="
          M 260 468
          C 275 460 300 456 320 458
          C 340 452 360 445 380 442
          C 400 435 425 428 450 424
          C 475 419 500 418 525 421
          C 555 424 585 428 610 434
          C 640 440 665 448 690 452
          C 715 456 735 462 750 468
          L 750 480
          C 730 484 700 486 660 486
          C 610 486 555 486 500 486
          C 445 486 390 486 340 486
          C 300 486 275 484 260 480
          Z
        "
        fill="url(#w-rock)"
      />

      {/* Grass / land layer with an uneven ridge */}
      <path
        d="
          M 285 460
          C 305 448 335 432 370 420
          C 395 410 420 400 445 396
          C 470 393 495 393 520 396
          C 550 400 580 408 605 418
          C 630 428 660 442 685 458
          C 700 464 715 468 720 470
          L 720 468
          C 700 464 675 460 650 458
          C 600 452 550 450 500 450
          C 450 450 400 452 355 458
          C 325 462 305 464 285 466
          Z
        "
        fill="url(#w-grass)"
      />

      {/* Uneven grass ridge — small tufts along the top */}
      <g fill="#2C6A5B" opacity="0.85">
        <path d="M 320 456 Q 328 448 336 456" />
        <path d="M 360 447 Q 368 438 376 447" />
        <path d="M 400 434 Q 408 424 416 434" />
        <path d="M 440 424 Q 448 414 456 424" />
        <path d="M 480 420 Q 488 410 496 420" />
        <path d="M 520 422 Q 528 412 536 422" />
        <path d="M 560 428 Q 568 418 576 428" />
        <path d="M 600 438 Q 608 428 616 438" />
        <path d="M 640 448 Q 648 438 656 448" />
        <path d="M 680 458 Q 688 448 696 458" />
      </g>

      {/* Warm ground glow — a soft breath of light from the island */}
      <ellipse cx="500" cy="440" rx="240" ry="60" fill="url(#w-islandglow)" />

      {/* Shoreline — organic sand line, not an ellipse */}
      <path
        d="
          M 260 478
          C 300 484 340 486 380 484
          C 420 482 460 480 500 480
          C 540 480 580 482 620 484
          C 660 486 700 484 740 478
          L 740 484
          C 700 490 660 490 620 490
          C 580 488 540 486 500 486
          C 460 486 420 488 380 490
          C 340 490 300 490 260 484
          Z
        "
        fill="#F7EFC7"
        opacity="0.55"
      />

      {/* Layer 2 — ground level (on/around island) */}
      {has('water')  && <WorldElement type="water" />}
      {has('path')   && <WorldElement type="path" />}
      {has('garden') && <WorldElement type="garden" />}
      {has('fire')   && <WorldElement type="fire" />}
      {has('trees')  && <WorldElement type="trees" />}

      {/* Feather top + bottom so the scene bleeds into the page */}
      <rect x="0" y="0"   width="1000" height="60" fill="url(#w-edgetop)" />
      <rect x="0" y="500" width="1000" height="60" fill="url(#w-edgebot)" />

      {/* Empty state — a whispered invitation */}
      {elements.length === 0 && (
        <text
          x="500" y="536"
          textAnchor="middle"
          fill="#F7EFC7"
          opacity="0.7"
          fontFamily="Georgia, 'Times New Roman', serif"
          fontStyle="italic"
          fontSize="15"
          letterSpacing="0.4"
        >
          Your world begins here.
        </text>
      )}
    </svg>
  )
}
