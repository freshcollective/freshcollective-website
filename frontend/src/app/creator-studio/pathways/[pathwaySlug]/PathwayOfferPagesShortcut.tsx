import type { CreatorOfferPageSummary } from '@/types/platform'
import OfferPagesShortcut from '../../offers/OfferPagesShortcut'

/**
 * Pathway Settings → Offer Pages shortcut.
 *
 * Thin wrapper over the shared ``OfferPagesShortcut`` component so
 * the Pathway settings page keeps its existing import site while
 * gaining the same 0 / 1 / many pattern (and shortcut deep-linking)
 * as the Series and Gathering shortcuts. All behaviour lives in the
 * shared component.
 */

interface Props {
  pathwayId: string
  /** Optional — feeds the empty-state helper text so the Creator
   *  sees the Pathway name in the card. */
  pathwayTitle?: string
  offers: CreatorOfferPageSummary[]
  paidOffersEnabled: boolean
}

export default function PathwayOfferPagesShortcut({
  pathwayId, pathwayTitle, offers, paidOffersEnabled,
}: Props) {
  return (
    <OfferPagesShortcut
      targetKind="pathway"
      targetId={pathwayId}
      targetTitle={pathwayTitle}
      offers={offers}
      paidOffersEnabled={paidOffersEnabled}
    />
  )
}
