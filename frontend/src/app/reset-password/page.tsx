import { notFound } from 'next/navigation'
import AuthPageShell, { AuthTitleAccent } from '@/components/layout/AuthPageShell'
import ResetPasswordForm from './ResetPasswordForm'

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>
}) {
  const { token } = await searchParams

  // Token must be present and look like a 64-char hex string
  if (!token || !/^[0-9a-f]{64}$/.test(token)) {
    notFound()
  }

  return (
    <AuthPageShell
      welcomeTitle={
        <>
          <AuthTitleAccent>Set a new password</AuthTitleAccent>
          <br />
          and you’re back in.
        </>
      }
      welcomeSubtitle="Almost there. Choose a new password and we’ll return you to your world."
    >
      <ResetPasswordForm token={token} />
    </AuthPageShell>
  )
}
