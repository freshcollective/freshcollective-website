import { redirect } from 'next/navigation'

export default function AdminSubscriptionsRedirect() {
  redirect('/admin/billing')
}
