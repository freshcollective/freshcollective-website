/**
 * The member's own star — a small, warm glow placed in the lower half of
 * the sky, distinct in colour from the constellations so the member can
 * recognise themselves without hierarchy language ("your rank",
 * "your level"). Not interactive.
 */
export default function UserStar() {
  return (
    <div
      className="pointer-events-none absolute"
      style={{ left: '48%', top: '76%', width: '4%', height: '4%' }}
      aria-hidden="true"
    >
      <div
        className="world-shimmer absolute inset-0 rounded-full"
        style={{
          background:
            'radial-gradient(circle, #FAFAF8 0%, rgba(247,251,250,0.35) 45%, transparent 75%)',
          transformOrigin: 'center',
        }}
      />
      <div
        className="world-twinkle absolute rounded-full"
        style={{
          left: '35%',
          top: '35%',
          width: '30%',
          height: '30%',
          background: '#FAFAF8',
          boxShadow: '0 0 8px rgba(247,251,250,0.75)',
        }}
      />
      <p
        className="absolute left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] font-medium uppercase tracking-[0.24em] text-white/70"
        style={{ top: 'calc(100% + 8px)' }}
      >
        You
      </p>
    </div>
  )
}
