import { permanentRedirect } from 'next/navigation'

/**
 * Legacy route — the collective's assets moved to /creator-studio/assets
 * when Brand Library was renamed and Collective Home was folded into
 * the same page. Anyone landing here (bookmark, email link, in-app
 * link that hasn't been updated yet) is bounced to the canonical
 * location with a 308 so search engines and the browser learn the new
 * URL.
 */
export default function LegacyMediaRedirect() {
  permanentRedirect('/creator-studio/assets')
}
