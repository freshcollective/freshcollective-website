import { redirect } from 'next/navigation'

/**
 * Legacy route. Build Your Place has been renamed to Build Your Collective
 * as part of Atlas v1.2. Kept as a redirect so bookmarks continue to work.
 */
export default function BuildYourPlaceRedirect() {
  redirect('/build-your-collective')
}
