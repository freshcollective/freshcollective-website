import { redirect } from 'next/navigation'

/**
 * World Insights opens on Growth.
 *
 * A landing page listing the six sections would be a click between the
 * caretaker and the first figure. Growth is the question most often
 * asked first, so it is what the area opens on.
 */
export default function InsightsIndexPage() {
  redirect('/admin/insights/growth')
}
