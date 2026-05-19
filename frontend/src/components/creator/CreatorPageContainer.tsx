import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
  className?: string
}

/**
 * Standard width/padding wrapper for all Creator Studio pages.
 * Gives the workspace enough horizontal room while keeping sensible margins.
 */
export default function CreatorPageContainer({ children, className }: Props) {
  return (
    <div className={`w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10 ${className ?? ''}`}>
      {children}
    </div>
  )
}
