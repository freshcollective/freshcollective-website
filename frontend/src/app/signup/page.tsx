import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import SignupForm from './SignupForm'
import { getPathwayOverview } from '@/lib/serverApi'
import type { PathwayWithSteps } from '@/types/platform'

interface Props {
  searchParams: Promise<{ next?: string }>
}

export type CheckoutContext = {
  pathwayTitle: string
  optionName: string | null
  optionDescription: string | null
  priceLabel: string | null
}

function fmtPrice(cents: number, currency: string): string {
  const sym = currency.toUpperCase() === 'AUD' ? '$' : currency
  const n = cents / 100
  return `${sym}${n % 1 === 0 ? n.toFixed(0) : n.toFixed(2)} ${currency.toUpperCase()}`
}

async function getCheckoutContext(next?: string): Promise<CheckoutContext | null> {
  if (!next) return null
  const match = next.match(/^\/spaces\/([^/?#]+)\/pathways\/([^/?#]+)\/checkout/)
  if (!match) return null
  const [, spaceSlug, pathwaySlug] = match
  try {
    const pathway = (await getPathwayOverview(spaceSlug, pathwaySlug)) as PathwayWithSteps | null
    if (!pathway) return null

    const qIdx = next.indexOf('?')
    const qs = qIdx >= 0 ? new URLSearchParams(next.slice(qIdx + 1)) : null
    const optionId = qs?.get('payment_option_id') ?? null
    const scheduleId = qs?.get('payment_option_schedule_id') ?? null

    if (optionId && pathway.payment_options.length > 0) {
      const opt = pathway.payment_options.find(o => o.id === optionId) ?? null
      const sched = (opt && scheduleId)
        ? (opt.schedules.find(s => s.id === scheduleId) ?? null)
        : null
      const priceCents = sched?.total_amount_cents ?? opt?.effective_price_cents ?? null
      const currency = opt?.currency ?? 'AUD'
      return {
        pathwayTitle: pathway.title,
        optionName: opt?.name ?? null,
        optionDescription: opt?.description ?? null,
        priceLabel: priceCents != null ? fmtPrice(priceCents, currency) : null,
      }
    }

    return {
      pathwayTitle: pathway.title,
      optionName: null,
      optionDescription: null,
      priceLabel: pathway.price_cents != null
        ? fmtPrice(pathway.price_cents, pathway.currency ?? 'AUD')
        : null,
    }
  } catch {
    return null
  }
}

export default async function SignUpPage({ searchParams }: Props) {
  const { next } = await searchParams
  const checkoutContext = await getCheckoutContext(next)

  return (
    <SiteShell>
      <section className="relative flex min-h-[80vh] items-center overflow-hidden bg-ivory py-20 md:bg-transparent">
        <div className="absolute inset-y-0 left-0 hidden w-1/2 bg-ivory md:block" aria-hidden="true" />
        <div className="absolute inset-y-0 right-0 hidden w-1/2 bg-navy-950 md:block" aria-hidden="true" />
        <Container className="relative z-10">
          <div className="flex items-center justify-center">
            <SignupForm nextUrl={next} checkoutContext={checkoutContext} />
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
