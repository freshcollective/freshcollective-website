import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import LoginForm from './LoginForm'
import { getPathwayOverview } from '@/lib/serverApi'
import type { PathwayWithSteps } from '@/types/platform'

export type CheckoutContext = {
  pathwayTitle: string
}

async function getCheckoutContext(next?: string): Promise<CheckoutContext | null> {
  if (!next) return null
  const match = next.match(/^\/spaces\/([^/?#]+)\/pathways\/([^/?#]+)\/checkout/)
  if (!match) return null
  const [, spaceSlug, pathwaySlug] = match
  try {
    const pathway = (await getPathwayOverview(spaceSlug, pathwaySlug)) as PathwayWithSteps | null
    if (!pathway) return null
    return { pathwayTitle: pathway.title }
  } catch {
    return null
  }
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>
}) {
  const { next } = await searchParams
  const checkoutContext = await getCheckoutContext(next)

  return (
    <SiteShell>
      <section className="relative flex min-h-[80vh] items-center overflow-hidden bg-ivory py-20 md:bg-transparent">
        <div className="absolute inset-0 hidden md:flex" aria-hidden="true">
          <div className="w-1/2 bg-ivory" />
          <div className="w-1/2 bg-navy-950" />
        </div>
        <Container className="relative z-10">
          <div className="flex items-center justify-center">
            <LoginForm nextUrl={next} checkoutContext={checkoutContext} />
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
