import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import ForgotPasswordForm from './ForgotPasswordForm'

export default function ForgotPasswordPage() {
  return (
    <SiteShell>
      <section className="relative flex min-h-[80vh] items-center overflow-hidden py-20">
        <div className="absolute inset-0 flex" aria-hidden="true">
          <div className="w-1/2 bg-ivory" />
          <div className="w-1/2 bg-navy-950" />
        </div>
        <Container className="relative z-10">
          <div className="flex items-center justify-center">
            <ForgotPasswordForm />
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
