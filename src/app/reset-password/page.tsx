import { notFound } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
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
    <SiteShell>
      <section className="relative flex min-h-[80vh] items-center overflow-hidden py-20">
        <div className="absolute inset-0 flex" aria-hidden="true">
          <div className="w-1/2 bg-ivory" />
          <div className="w-1/2 bg-navy-950" />
        </div>
        <Container className="relative z-10">
          <div className="flex items-center justify-center">
            <ResetPasswordForm token={token} />
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
