import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import LoginForm from './LoginForm'

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>
}) {
  const { next } = await searchParams

  return (
    <SiteShell>
      <section className="relative flex min-h-[80vh] items-center overflow-hidden bg-ivory py-20 md:bg-transparent">
        <div className="absolute inset-0 hidden md:flex" aria-hidden="true">
          <div className="w-1/2 bg-ivory" />
          <div className="w-1/2 bg-navy-950" />
        </div>
        <Container className="relative z-10">
          <div className="flex items-center justify-center">
            <LoginForm nextUrl={next} />
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
