'use client'

const FOUNDATION = [
  { name: 'REAL Journey', category: 'Foundation' },
  { name: 'Recognise', category: 'Phase 1' },
  { name: 'Explore', category: 'Phase 2' },
  { name: 'Align', category: 'Phase 3' },
  { name: 'Lead', category: 'Phase 4' },
  { name: 'Practices & tools', category: 'Foundation' },
  { name: 'Behaviour change', category: 'Foundation' },
  { name: 'Bite-sized sessions', category: 'Foundation' },
  { name: 'Self-paced', category: 'Foundation' },
  { name: 'Revisit anytime', category: 'Foundation' },
]

const MEMBERSHIP = [
  { name: 'Monthly live calls', category: 'The Heart' },
  { name: 'Community of women', category: 'The Heart' },
  { name: 'Deepening pathways', category: 'The Rooms' },
  { name: 'Nervous system work', category: 'The Rooms' },
  { name: 'Human Design', category: 'The Rooms' },
  { name: 'Personal leadership', category: 'The Rooms' },
  { name: 'Content library', category: 'Membership' },
  { name: 'Integration support', category: 'Membership' },
  { name: 'Live accountability', category: 'The Heart' },
  { name: 'Embodiment practices', category: 'The Rooms' },
]

interface ItemProps {
  name: string
  category: string
  teal?: boolean
}

function Item({ name, category, teal }: ItemProps) {
  return (
    <div
      className="flex shrink-0 items-center gap-2 rounded-lg px-3.5 py-2"
      style={{
        background: teal ? 'rgba(56,160,158,0.10)' : 'rgba(255,255,255,0.05)',
        border: teal ? '1px solid rgba(56,160,158,0.22)' : '1px solid rgba(255,255,255,0.08)',
      }}
    >
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: teal ? '#55B8B6' : 'rgba(255,255,255,0.25)' }}
      />
      <span
        className="text-[12px] font-medium"
        style={{ color: teal ? '#7FCFCD' : 'rgba(255,255,255,0.55)' }}
      >
        {name}
      </span>
      <span
        className="text-[10px]"
        style={{ color: teal ? 'rgba(127,207,205,0.55)' : 'rgba(255,255,255,0.25)' }}
      >
        {category}
      </span>
    </div>
  )
}

export default function AnimatedTypeRibbon() {
  const foundationDoubled = [...FOUNDATION, ...FOUNDATION]
  const membershipDoubled = [...MEMBERSHIP, ...MEMBERSHIP]

  return (
    <div
      aria-hidden="true"
      className="overflow-hidden py-5"
      style={{
        background: 'linear-gradient(180deg, #071A1A 0%, #0D1F35 100%)',
        borderTop: '1px solid rgba(56,160,158,0.08)',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        maskImage: 'linear-gradient(to right, transparent 0%, black 6%, black 94%, transparent 100%)',
        WebkitMaskImage: 'linear-gradient(to right, transparent 0%, black 6%, black 94%, transparent 100%)',
      }}
    >
      <div className="space-y-3">
        {/* Row 1 — Foundation (forward, teal) */}
        <div className="relative overflow-hidden">
          <div
            className="fc-ribbon flex items-center gap-3"
            style={{ width: 'max-content', animation: 'ribbon-fwd 80s linear infinite' }}
          >
            {foundationDoubled.map((item, i) => (
              <Item key={i} {...item} teal />
            ))}
          </div>
        </div>

        {/* Row 2 — Membership (reverse, muted) */}
        <div className="relative overflow-hidden">
          <div
            className="fc-ribbon flex items-center gap-3"
            style={{ width: 'max-content', animation: 'ribbon-rev 80s linear infinite' }}
          >
            {membershipDoubled.map((item, i) => (
              <Item key={i} {...item} teal={false} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
