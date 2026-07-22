import { AppShell } from '@/components/platform/AppShell'
import CreatorStudioSidebar from './CreatorStudioSidebar'
import type { SpaceSummary } from '@/types/platform'

/**
 * Creator Studio Shell
 *
 * Thin wrapper around the platform <AppShell variant="sidebar">. Owns nothing
 * except the composition — sidebar content lives in
 * <CreatorStudioSidebar>. Same shell renders on desktop and mobile;
 * on mobile the sidebar becomes a slide-in drawer via AppShell.
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
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
  /** Platform Owner accounts are unlimited — the sidebar suppresses any
   *  "N of M collectives used" text when this is true. */
  isPlatformOwner: boolean
}

export default function CreatorStudioShell({
  children, user, spaces, activeSpace, collectiveLimit, isPlatformOwner,
}: Props) {
  return (
    <AppShell
      variant="sidebar"
      sidebar={
        <CreatorStudioSidebar
          user={user}
          spaces={spaces}
          activeSpace={activeSpace}
          collectiveLimit={collectiveLimit}
          isPlatformOwner={isPlatformOwner}
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
