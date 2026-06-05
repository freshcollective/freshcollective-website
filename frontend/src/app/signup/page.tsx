import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import SignupForm from './SignupForm'

export default function SignUpPage() {
  return (
    <SiteShell>
      <section className="relative flex min-h-[80vh] items-center overflow-hidden bg-ivory py-20 md:bg-transparent">
        <div className="absolute inset-y-0 left-0 hidden w-1/2 bg-ivory md:block" aria-hidden="true" />
        <div className="absolute inset-y-0 right-0 hidden w-1/2 bg-navy-950 md:block" aria-hidden="true" />
        <Container className="relative z-10">
          <div className="flex items-center justify-center">
            <SignupForm />
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
