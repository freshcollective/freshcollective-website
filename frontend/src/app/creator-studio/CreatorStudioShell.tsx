import { AppShell } from '@/components/platform/AppShell'
import CreatorStudioSidebar from './CreatorStudioSidebar'

/**
 * Creator Studio Shell
 *
 * Thin wrapper around the platform <AppShell variant="sidebar">. The
 * sidebar is navigation-only — the active-collective identity is
 * carried by the shared page header (``CollectiveArtworkHeader``), not
 * by any chrome inside the sidebar itself.
 *
 * Consumed by:
 *   - app/creator-studio/layout.tsx
 *   - app/creator/layout.tsx
 */

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

interface Props {
  children: React.ReactNode
  user: User
  /** Whether the creator has at least one collective. Controls sidebar
   *  dimming of collective-scoped destinations. */
  hasCollective: boolean
  /** True when the current creator's plan (or Platform Owner status)
   *  unlocks commercial surfaces such as Offer Pages. Controls which
   *  sidebar entries render. Hidden entirely on Community. */
  paidOffersEnabled?: boolean
}

export default function CreatorStudioShell({
  children, user, hasCollective, paidOffersEnabled = false,
}: Props) {
  return (
    <AppShell
      variant="sidebar"
      sidebar={
        <CreatorStudioSidebar
          user={user}
          hasCollective={hasCollective}
          paidOffersEnabled={paidOffersEnabled}
        />
      }
      mobileBrand={
        <span className="font-serif text-[16px] text-[color:var(--fc-ink-heading)]">
          Creator Studio
        </span>
      }
    >
      {children}
    </AppShell>
  )
}
