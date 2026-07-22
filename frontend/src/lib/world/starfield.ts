/**
 * Deterministic backdrop starfield generator.
 *
 * Uses a seeded mulberry32 PRNG so server and client render identical star
 * positions — no hydration mismatch, no Math.random() in components.
 */

function mulberry32(seed: number): () => number {
  let s = seed >>> 0
  return function next(): number {
    s = (s + 0x6D2B79F5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export interface BackdropStar {
  x: number   // 0..1
  y: number   // 0..1
  r: number   // radius, sky-pixel space (viewBox units)
  o: number   // baseline opacity 0..1
  d: number   // twinkle animation delay in seconds
}

export function generateBackdropStars(seed: number, count: number): BackdropStar[] {
  const rnd = mulberry32(seed)
  const stars: BackdropStar[] = []
  for (let i = 0; i < count; i++) {
    stars.push({
      x: rnd(),
      // Keep stars away from the very top/bottom edges so labels have room.
      y: rnd() * 0.90 + 0.04,
      r: 0.4 + rnd() * 1.2,
      o: 0.30 + rnd() * 0.55,
      d: rnd() * 6,
    })
  }
  return stars
}
