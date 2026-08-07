import Link from 'next/link'
import type { ReactNode } from 'react'
import { cn } from '@/components/platform/utils'

/**
 * PrimaryActionLink — the standard "create / add" primary CTA used
 * across Creator Studio headers and empty-state cards.
 *
 * Renders a Next.js Link styled exactly like the shared platform
 * Button (variant="primary", size="md") so header CTAs and drawer
 * footer buttons feel like siblings. The plus icon is on by default
 * for the common "create/add" action; opt out with `showIcon={false}`
 * on the rare Continue/View link that doesn't want it.
 *
 * When you need a real onClick (opening a modal, submitting a form),
 * use the platform `<Button variant="primary" size="md">` directly
 * instead — same visual, different semantic.
 */
interface Props {
  href: string
  children: ReactNode
  showIcon?: boolean
  className?: string
  onClick?: () => void
}

// Mirrors Button.tsx BASE + VARIANT.primary + SIZE.md so the two stay
// visually identical without importing Button (which is a <button>).
const CLASSES =
  // BASE
  'inline-flex items-center justify-center gap-2 whitespace-nowrap font-[var(--fc-fw-semibold)] ' +
  'transition-opacity duration-[var(--fc-motion-hover)] ease-out ' +
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ' +
  'focus-visible:ring-[color:var(--fc-accent-500)]/40 focus-visible:ring-offset-[color:var(--fc-surface-page)] ' +
  // VARIANT.primary
  'text-[color:var(--fc-ink-inverse)] [background:var(--fc-accent-gradient)] hover:opacity-90 ' +
  // SIZE.md
  'h-10 px-4 text-[13px] rounded-[var(--fc-radius-md)]'

export default function PrimaryActionLink({
  href, children, showIcon = true, className, onClick,
}: Props) {
  return (
    <Link href={href} onClick={onClick} className={cn(CLASSES, className)}>
      {showIcon && <PlusIcon />}
      <span>{children}</span>
    </Link>
  )
}

/** The plus glyph used across every "create/add" primary action. Exported
 *  so button-driven CTAs (modal openers) can render the same icon. */
export function PlusIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}
