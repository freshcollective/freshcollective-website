import { redirect } from 'next/navigation'

/**
 * Backwards-compat redirect from the pre-U1 route
 * ``/creator-studio/passes`` to the renamed
 * ``/creator-studio/access``. Old bookmarks / links still resolve.
 */
export default function LegacyPassesRedirect(): never {
  redirect('/creator-studio/access')
}
