import AuthPageShell, { AuthTitleAccent } from '@/components/layout/AuthPageShell'
import ForgotPasswordForm from './ForgotPasswordForm'

/**
 * Forgot Password — same shell as /login (full-bleed Atlas artwork,
 * navy overlay, transparent header, minimal footer). The card itself
 * is provided by AuthCard so all four auth surfaces stay in visual
 * lock-step.
 */
export default function ForgotPasswordPage() {
  return (
    <AuthPageShell
      welcomeTitle={
        <>
          <AuthTitleAccent>Reset your password</AuthTitleAccent>
          <br />
          in a moment.
        </>
      }
      welcomeSubtitle="A single link, sent to your email, will let you set a new one."
    >
      <ForgotPasswordForm />
    </AuthPageShell>
  )
}
