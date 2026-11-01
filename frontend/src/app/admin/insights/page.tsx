import { redirect } from 'next/navigation'

/**
 * World Insights opens on the Overview.
 *
 * It opened on Growth while Growth was the only broad view; now that
 * there is a page whose whole job is "how are we doing, and what
 * needs attention", that is the honest landing place. A caretaker who
 * wants membership detail is one labelled tab away, and every direct
 * link into a section still resolves on its own.
 */
export default function InsightsIndexPage() {
  redirect('/admin/insights/overview')
}
