/**
 * World Management → Communications → Email Templates.
 *
 * The /admin layout already guards this route (signed in, role admin)
 * and the backend guards every endpoint behind `get_admin_user`. This
 * page repeats the role check for one reason beyond defence in depth:
 * it needs the signed-in admin's own address, because a test send goes
 * there and nowhere else, and the page says so before it is pressed.
 */

import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import EmailTemplatesClient from './EmailTemplatesClient'

export const metadata = {
  title: 'Email Templates — World Management',
}

export default async function EmailTemplatesPage() {
  const user = await requireAuthenticatedUser({ loginPath: '/admin/login' })

  if (user.role !== 'admin') {
    return (
      <div className="mx-auto max-w-[520px] py-16 text-center">
        <h1 className="mb-2 text-xl font-bold text-[#0F172A]">Access denied</h1>
        <p className="text-[14px] text-[rgba(12,24,38,0.60)]">
          You need admin access to manage email templates.
        </p>
      </div>
    )
  }

  return <EmailTemplatesClient adminEmail={user.email} />
}
