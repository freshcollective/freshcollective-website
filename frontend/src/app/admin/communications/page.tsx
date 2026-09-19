/**
 * Communications has one page today. Rather than a landing page listing
 * a single link, the bare section URL goes straight to it.
 */

import { redirect } from 'next/navigation'

export default function CommunicationsPage() {
  redirect('/admin/communications/email-templates')
}
