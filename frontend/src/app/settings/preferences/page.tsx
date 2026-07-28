import { redirect } from 'next/navigation'

/**
 * Legacy /settings/preferences — permanently redirects to the new
 * Stay Connected page so old links / bookmarks / nav prefetches
 * keep working. Kept as a route rather than deleted so the redirect
 * survives the initial rollout.
 */
export default function SettingsPreferencesRedirect() {
  redirect('/settings/stay-connected')
}
