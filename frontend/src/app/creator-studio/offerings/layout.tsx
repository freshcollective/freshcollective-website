import { requireOfferingsAvailable } from '@/lib/offeringsAccess'

/**
 * 🚪 The Creator Studio Offerings doorway.
 *
 * One guard for every route under `/creator-studio/offerings/**` —
 * the list, the editor, pricing, files, About and preview — rather
 * than a check repeated in each page, which is the arrangement that
 * lets a newly added page quietly ship ungated.
 *
 * A creator whose selected Collective is outside the pilot gets a 404
 * here, the same answer the API gives them. Before this existed the
 * nav entry rendered for everyone and the page loaded with a
 * working-looking create form whose POST then failed with "Not found" —
 * reported from production against a non-pilot Collective, and
 * reproduced on an ordinary creator account as well as an
 * administrator's.
 *
 * Note this is presentation only. It hides a door the backend had
 * already locked; it is not what locks it. `require_pilot_space` and
 * `require_offerings_enabled` remain the enforcement.
 */
export default async function CreatorStudioOfferingsLayout(
  { children }: { children: React.ReactNode },
) {
  await requireOfferingsAvailable()
  return <>{children}</>
}
