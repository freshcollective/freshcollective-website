import { redirect } from 'next/navigation'

/**
 * `/creator-studio/setup` has been merged into `/creator-studio/settings`.
 * Kept as a redirect so bookmarked or auto-completed URLs don't 404.
 */
export default function SetupRedirect() {
  redirect('/creator-studio/settings')
}
