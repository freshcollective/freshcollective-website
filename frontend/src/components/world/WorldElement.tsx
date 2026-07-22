import type { WorldElementType } from '@/lib/world/collectives'

/**
 * A symbolic element on the personal island. Each element renders as an
 * SVG `<g>` group so it composes into the parent PersonalIsland SVG
 * (viewBox 0 0 1000 560).
 *
 * Vocabulary matches the collective mapping in `lib/world/collectives.ts`:
 *   - trees, garden          → The Grove
 *   - water, path            → EMBODY
 *   - sunrise, mountain, fire → Life in Alignment
 */

interface Props {
  type: WorldElementType
}

export default function WorldElement({ type }: Props) {
  switch (type) {
    case 'trees':    return <Trees />
    case 'garden':   return <Garden />
    case 'water':    return <Water />
    case 'path':     return <Path />
    case 'sunrise':  return <Sunrise />
    case 'mountain': return <Mountain />
    case 'fire':     return <Fire />
  }
}

// ---------------------------------------------------------------------------
// The Grove
// ---------------------------------------------------------------------------

function Trees() {
  return (
    <g aria-label="grove">
      {/* Tallest tree — soft rounded canopy, wisp of gold */}
      <g className="world-drift" style={{ transformOrigin: '600px 452px' }}>
        <path
          d="
            M 600 402
            C 588 400 580 408 580 418
            C 572 420 566 428 572 438
            C 566 442 566 452 578 454
            C 590 458 610 458 622 454
            C 634 452 634 442 628 438
            C 634 428 628 420 620 418
            C 620 408 612 400 600 402 Z
          "
          fill="#274B3E"
          opacity="0.95"
        />
        <path
          d="M 595 452 L 605 452 L 606 466 L 594 466 Z"
          fill="#2A1810"
        />
        <circle cx="595" cy="418" r="1.5" fill="#F7EFC7" opacity="0.7" />
      </g>

      {/* Right tree */}
      <g className="world-drift" style={{ transformOrigin: '648px 460px', animationDelay: '1.8s' }}>
        <path
          d="
            M 648 424
            C 638 424 632 432 636 440
            C 632 446 636 454 644 454
            C 654 458 664 456 668 452
            C 674 448 672 438 666 436
            C 668 428 660 422 648 424 Z
          "
          fill="#1F5F55"
          opacity="0.92"
        />
        <path d="M 644 454 L 652 454 L 653 466 L 643 466 Z" fill="#2A1810" />
      </g>

      {/* Left tree */}
      <g className="world-drift" style={{ transformOrigin: '555px 460px', animationDelay: '0.9s' }}>
        <path
          d="
            M 555 430
            C 545 430 540 438 544 446
            C 540 452 546 458 554 458
            C 562 462 572 460 574 456
            C 580 452 578 442 572 440
            C 574 434 566 428 555 430 Z
          "
          fill="#256D63"
          opacity="0.9"
        />
        <path d="M 552 458 L 560 458 L 561 466 L 551 466 Z" fill="#2A1810" />
      </g>

      {/* A tiny sapling further along */}
      <g className="world-drift" style={{ transformOrigin: '520px 466px', animationDelay: '0.4s' }}>
        <path
          d="M 520 458 C 516 458 514 462 517 466 C 522 469 527 466 526 462 C 525 460 523 458 520 458 Z"
          fill="#2C6A5B"
          opacity="0.85"
        />
        <path d="M 519 466 L 522 466 L 522 470 L 519 470 Z" fill="#2A1810" />
      </g>
    </g>
  )
}

function Garden() {
  const seeds: Array<{ cx: number; cy: number; r: number; fill: string; d: number }> = [
    { cx: 435, cy: 476, r: 1.6, fill: '#E7C65A', d: 0 },
    { cx: 447, cy: 480, r: 1.4, fill: '#F7EFC7', d: 0.6 },
    { cx: 459, cy: 476, r: 1.7, fill: '#BF9830', d: 1.2 },
    { cx: 471, cy: 480, r: 1.4, fill: '#F7EFC7', d: 1.8 },
    { cx: 484, cy: 477, r: 1.6, fill: '#E7C65A', d: 2.4 },
    { cx: 495, cy: 481, r: 1.4, fill: '#F7EFC7', d: 3.0 },
    { cx: 507, cy: 478, r: 1.5, fill: '#BF9830', d: 3.6 },
  ]
  return (
    <g aria-label="garden">
      {seeds.map((s, i) => (
        <circle
          key={i}
          cx={s.cx}
          cy={s.cy}
          r={s.r}
          fill={s.fill}
          className="world-twinkle"
          style={{ animationDelay: `${s.d.toFixed(2)}s`, opacity: 0.9 }}
        />
      ))}
    </g>
  )
}

// ---------------------------------------------------------------------------
// EMBODY
// ---------------------------------------------------------------------------

function Water() {
  return (
    <g aria-label="water" className="world-flow" style={{ transformOrigin: '360px 500px' }}>
      <path
        d="M 260 496 Q 300 490 340 494 T 420 496 T 500 496"
        stroke="#8DE8E6"
        strokeWidth="1.4"
        strokeOpacity="0.55"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M 240 504 Q 285 498 330 502 T 420 504"
        stroke="#55D7D2"
        strokeWidth="1.2"
        strokeOpacity="0.42"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M 265 512 Q 305 508 345 512 T 425 512"
        stroke="#8DE8E6"
        strokeWidth="1.0"
        strokeOpacity="0.32"
        fill="none"
        strokeLinecap="round"
      />
      {/* Sparkle points on the water */}
      <circle cx="330" cy="498" r="0.9" fill="#FAFAF8" opacity="0.8" className="world-twinkle" style={{ animationDelay: '0.4s' }} />
      <circle cx="380" cy="502" r="0.8" fill="#FAFAF8" opacity="0.7" className="world-twinkle" style={{ animationDelay: '1.6s' }} />
      <circle cx="290" cy="508" r="0.9" fill="#FAFAF8" opacity="0.6" className="world-twinkle" style={{ animationDelay: '2.8s' }} />
    </g>
  )
}

function Path() {
  return (
    <g aria-label="path">
      {/* Warm cream stepping stones fading toward the horizon */}
      <path
        d="M 500 470 Q 512 494 540 508 T 604 522"
        stroke="#F7EFC7"
        strokeWidth="1.8"
        strokeOpacity="0.45"
        strokeDasharray="1 7"
        fill="none"
        strokeLinecap="round"
      />
      {/* Subtle glow trailing along the path */}
      <path
        d="M 500 470 Q 512 494 540 508 T 604 522"
        stroke="#F7EFC7"
        strokeWidth="6"
        strokeOpacity="0.06"
        fill="none"
        strokeLinecap="round"
      />
    </g>
  )
}

// ---------------------------------------------------------------------------
// Life in Alignment
// ---------------------------------------------------------------------------

function Sunrise() {
  return (
    <g aria-label="sunrise">
      <defs>
        <radialGradient id="w-sunrise-glow" cx="0.5" cy="1" r="0.55">
          <stop offset="0%"   stopColor="#E7C65A" stopOpacity="0.42" />
          <stop offset="45%"  stopColor="#BF9830" stopOpacity="0.14" />
          <stop offset="100%" stopColor="#BF9830" stopOpacity="0" />
        </radialGradient>
      </defs>
      {/* Broad warm horizon */}
      <ellipse
        cx="700" cy="392" rx="260" ry="110"
        fill="url(#w-sunrise-glow)"
        className="world-shimmer"
        style={{ transformOrigin: '700px 392px' }}
      />
      {/* The sun itself, sitting on the horizon */}
      <circle
        cx="700" cy="388" r="14"
        fill="#F7EFC7"
        opacity="0.85"
        className="world-twinkle"
      />
      {/* One high wisp of cloud, catching light */}
      <path
        d="M 620 340 Q 660 336 700 340 T 780 342"
        stroke="#F7EFC7"
        strokeWidth="1.6"
        strokeOpacity="0.30"
        fill="none"
        strokeLinecap="round"
      />
    </g>
  )
}

function Mountain() {
  return (
    <g aria-label="mountain">
      {/* Distant range — soft, feminine ridge, not jagged */}
      <path
        d="
          M 60 400
          C 100 384 140 372 180 380
          C 220 388 260 372 300 380
          C 340 388 370 380 400 388
          L 400 402 L 60 402 Z
        "
        fill="#0A1524"
        opacity="0.8"
      />
      <path
        d="
          M 60 402
          C 100 396 140 388 180 394
          C 220 400 260 388 300 394
          C 340 400 370 396 400 400
          L 400 405 L 60 405 Z
        "
        fill="#152633"
        opacity="0.7"
      />
      {/* Snow / light on the highest peak */}
      <path
        d="M 175 383 L 183 375 L 191 383 Z"
        fill="#F7EFC7"
        opacity="0.55"
      />
    </g>
  )
}

function Fire() {
  return (
    <g aria-label="hearth">
      {/* Halo glow — the reason a small flame reads at this size */}
      <ellipse
        cx="405" cy="472" rx="28" ry="14"
        fill="#E7C65A"
        opacity="0.22"
        className="world-shimmer"
        style={{ transformOrigin: '405px 472px' }}
      />
      {/* Ember stones */}
      <ellipse cx="405" cy="482" rx="12" ry="3" fill="#2A1810" opacity="0.8" />
      {/* Flame — soft teardrop */}
      <g className="world-ember" style={{ transformOrigin: '405px 480px' }}>
        <path
          d="
            M 405 462
            C 398 470 396 478 402 484
            C 405 480 405 478 405 476
            C 405 480 407 484 410 484
            C 414 478 412 470 405 462 Z
          "
          fill="#E7C65A"
        />
        <path
          d="
            M 405 468
            C 401 474 400 480 404 483
            C 405 480 405 478 405 476
            C 405 480 406 483 407 483
            C 410 480 409 474 405 468 Z
          "
          fill="#F7EFC7"
          opacity="0.9"
        />
      </g>
    </g>
  )
}
