/**
 * Small editorial building blocks used across platform pages.
 * Mirrors the visual language of the Fresh Collective public site:
 * the `——` gold accent line + small ALL-CAPS label, and the soft pill tag.
 */

interface GoldLabelProps {
  children: React.ReactNode
  /** Width of the gold accent line in Tailwind units (default w-4) */
  lineWidth?: string
  /** Label colour — teal for live/active sections, slate for section dividers */
  variant?: 'slate' | 'teal'
  className?: string
}

export function GoldLabel({
  children,
  lineWidth = 'w-4',
  variant = 'slate',
  className = '',
}: GoldLabelProps) {
  const textColor = variant === 'teal' ? 'text-teal-600' : 'text-slate-400'
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <div
        className={`${lineWidth} h-[2px] shrink-0 rounded-full`}
        style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
      />
      <span className={`text-[10px] font-semibold uppercase tracking-[0.16em] ${textColor}`}>
        {children}
      </span>
    </div>
  )
}

interface PillTagProps {
  children: React.ReactNode
  variant?: 'teal' | 'gold' | 'muted'
  className?: string
}

export function PillTag({ children, variant = 'teal', className = '' }: PillTagProps) {
  const styles: Record<string, React.CSSProperties> = {
    teal: { background: 'rgba(56,160,158,0.10)', color: '#38A09E' },
    gold: { background: 'rgba(231,198,90,0.12)', color: '#9A7A18' },
    muted: { background: 'rgba(148,163,184,0.12)', color: '#64748B' },
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${className}`}
      style={styles[variant]}
    >
      {children}
    </span>
  )
}
