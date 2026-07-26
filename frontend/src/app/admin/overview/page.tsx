import Link from 'next/link'
import {
  getMotherWorldOverview,
  getPublicPlatformArtwork,
  type MotherWorldOverview,
  type MotherWorldMoment,
} from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'

/**
 * Mother World — the visual + emotional centre of World Management.
 *
 * A panoramic hero opens the page. Below it, Needs Your Attention spans
 * the full width, then a two-column body: Life + Moments on the left,
 * Commerce + Health on the right. If no hero artwork is configured,
 * the page falls back to a plain text header — no broken image.
 */

const HUE = {
  green: { bg: 'rgba(56, 160, 158, 0.10)', border: 'rgba(56, 160, 158, 0.22)', text: '#0f766e', dot: '#22a598' },
  gold:  { bg: 'rgba(212, 176, 72, 0.14)', border: 'rgba(212, 176, 72, 0.30)', text: '#8A6A15', dot: '#d4b048' },
  blue:  { bg: 'rgba(56, 116, 180, 0.10)', border: 'rgba(56, 116, 180, 0.22)', text: '#1e40af', dot: '#4c78d4' },
  coral: { bg: 'rgba(214, 96, 87, 0.09)',  border: 'rgba(214, 96, 87, 0.28)',  text: '#a63c30', dot: '#d66057' },
  ink:   { text: '#0C1826', muted: 'rgba(12, 24, 38, 0.60)', softer: 'rgba(12, 24, 38, 0.42)' },
} as const

// Pure white page. The hero image supplies the warmth; cards lift with a
// crisp, near-invisible elevation and a very light cool border.
const PAGE_BG   = '#FFFFFF'
const CARD_BG   = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'
const HAIRLINE  = '1px solid rgba(12, 24, 38, 0.06)'

const HERO_TITLE = 'Mother World'
const HERO_BLURB = 'A living snapshot of everything happening across Fresh Collective. Check in, see what needs your care, then step into the day.'

const SERIF_ITALIC: React.CSSProperties = {
  color: HUE.ink.muted,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

// ---------------------------------------------------------------------------

export default async function MotherWorldPage() {
  const [data, artwork] = await Promise.all([
    getMotherWorldOverview(),
    getPublicPlatformArtwork(),
  ])

  const heroRow = artwork.find((a) => a.key === 'mother_world_hero')
  const heroUrl = resolveMediaUrl(heroRow?.image_url)

  if (!data) {
    return (
      <div style={{ background: PAGE_BG, minHeight: '100%' }}>
        <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
          <p style={SERIF_ITALIC}>Mother World is resting. Please refresh in a moment.</p>
        </div>
      </div>
    )
  }

  return (
    <div style={{ background: PAGE_BG, minHeight: '100%' }}>
      <div className="mx-auto max-w-[1200px] px-6 py-8 md:px-10 md:py-10">
        <Hero imageUrl={heroUrl} />

        <div className="mt-10">
          <NeedsAttentionSection data={data} />
        </div>

        <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="lg:col-start-1 lg:row-start-1">
            <LifeAcrossSection data={data} />
          </div>
          <div className="lg:col-start-2 lg:row-start-1">
            <CommerceSection data={data} />
          </div>
          <div className="lg:col-start-1 lg:row-start-2">
            <MomentsSection moments={data.recent_moments} />
          </div>
          <div className="lg:col-start-2 lg:row-start-2">
            <WorldHealthSection health={data.world_health} />
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Hero — panoramic mother_world_hero with title + blurb overlay.
// Falls back to a plain text header when no artwork is configured.
// ---------------------------------------------------------------------------

function Hero({ imageUrl }: { imageUrl: string | null }) {
  if (!imageUrl) {
    return (
      <header>
        <h1
          className="font-serif text-[32px] leading-tight md:text-[40px]"
          style={{ color: HUE.ink.text }}
        >
          {HERO_TITLE}
        </h1>
        <p className="mt-3 max-w-[620px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
          {HERO_BLURB}
        </p>
      </header>
    )
  }

  return (
    <header
      className="relative overflow-hidden rounded-3xl"
      style={{
        height: 'clamp(180px, 32vw, 260px)',
        boxShadow: '0 10px 40px rgba(12, 24, 38, 0.10)',
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={imageUrl}
        alt=""
        className="absolute inset-0 h-full w-full"
        style={{ objectFit: 'cover', objectPosition: '50% 30%' }}
      />
      {/* Bottom-heavy vertical scrim so the copy sits on darker water while
          the top of the image stays warm and open. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(to top, rgba(8, 18, 30, 0.78) 0%, rgba(8, 18, 30, 0.45) 32%, rgba(8, 18, 30, 0.10) 60%, rgba(8, 18, 30, 0) 82%)',
        }}
      />
      <div className="relative flex h-full w-full items-end p-7 md:p-10">
        <div className="max-w-[640px]">
          <h1
            className="font-serif text-[30px] leading-tight text-white md:text-[42px]"
            style={{
              color: '#FFFFFF',
              textShadow: '0 2px 18px rgba(0, 0, 0, 0.55), 0 1px 3px rgba(0, 0, 0, 0.6)',
            }}
          >
            {HERO_TITLE}
          </h1>
          <p
            className="mt-2 text-[13.5px] leading-relaxed italic md:mt-3 md:text-[15px]"
            style={{
              color: 'rgba(255, 255, 255, 0.95)',
              fontFamily: 'Georgia, serif',
              textShadow: '0 1px 12px rgba(0, 0, 0, 0.55)',
            }}
          >
            {HERO_BLURB}
          </p>
        </div>
      </div>
    </header>
  )
}

// ---------------------------------------------------------------------------
// Shared section header — serif h2 + Georgia italic subtitle. Optional
// right-side action for cases like "View Commerce →".
// ---------------------------------------------------------------------------

function SectionHeader({
  title, subtitle, action,
}: { title: string; subtitle: string; action?: { label: string; href: string } }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2
          className="font-serif text-[22px] leading-tight md:text-[24px]"
          style={{ color: HUE.ink.text }}
        >
          {title}
        </h2>
        <p className="mt-1.5 max-w-[520px] text-[13.5px] leading-relaxed" style={SERIF_ITALIC}>
          {subtitle}
        </p>
      </div>
      {action && (
        <Link
          href={action.href}
          className="shrink-0 text-[12.5px] font-semibold transition-colors hover:opacity-80"
          style={{ color: HUE.green.text }}
        >
          {action.label}
        </Link>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Today's Focus — priority-aware attention panel.
//
// Severity scales with the item: routine admin (pending invitations, access
// requests) sits on a soft warm-neutral surface with amber dots; critical
// signals (payment failures) escalate to coral dots + a coral action link
// without turning the whole panel red. Green "all healthy" card when nothing
// is waiting.
// ---------------------------------------------------------------------------

type AttentionSeverity = 'routine' | 'critical'
type AttentionItem = { label: string; href: string; severity: AttentionSeverity }

function NeedsAttentionSection({ data }: { data: MotherWorldOverview }) {
  // Panel surfaces the health of the world, not workflow mechanics.
  // Invitation and access-request counts are intentionally excluded: they
  // belong inside the creator/collective experience where the work happens.
  const items: AttentionItem[] = []
  if (data.failed_transactions_7d > 0) {
    items.push({
      label: data.failed_transactions_7d === 1
        ? '1 payment failed this week'
        : `${data.failed_transactions_7d} payments failed this week`,
      href: '/admin/payments',
      severity: 'critical',
    })
  }

  const quiet = items.length === 0

  return (
    <section>
      <SectionHeader
        title="Today's Focus"
        subtitle="Things that need your care today."
      />

      {quiet ? (
        <div
          className="rounded-2xl px-6 py-5"
          style={{ background: HUE.green.bg, border: `1px solid ${HUE.green.border}` }}
        >
          <p className="font-serif text-[18px] leading-tight" style={{ color: HUE.ink.text }}>
            Everything looks good today.
          </p>
          <p className="mt-1 text-[13px] italic" style={SERIF_ITALIC}>
            Nothing needs your attention.
          </p>
        </div>
      ) : (
        <div
          className="overflow-hidden rounded-2xl"
          style={{ background: '#FFF9F2', border: '1px solid #F2E3CF' }}
        >
          {items.map((item, i) => {
            const accent = item.severity === 'critical' ? HUE.coral : HUE.gold
            return (
              <Link
                key={i}
                href={item.href}
                className="group flex items-center justify-between px-6 py-4 transition-colors hover:bg-white/50"
                style={i > 0 ? { borderTop: '1px solid #F2E3CF' } : undefined}
              >
                <span className="flex items-center gap-3">
                  <span
                    className="inline-block h-2 w-2 shrink-0 rounded-full"
                    style={{ background: accent.dot }}
                    aria-hidden
                  />
                  <span className="text-[14px]" style={{ color: HUE.ink.text }}>
                    {item.label}
                  </span>
                </span>
                <span
                  className="ml-4 text-[12.5px] font-semibold transition-transform group-hover:translate-x-0.5"
                  style={{ color: accent.text }}
                >
                  Review →
                </span>
              </Link>
            )
          })}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Life Across Our World — the main data feature. 2×2 grid, numbers as hero.
// ---------------------------------------------------------------------------

function LifeAcrossSection({ data }: { data: MotherWorldOverview }) {
  const cards = [
    {
      icon: '🌳',
      label: 'Active Collectives',
      value: data.active_collectives,
      caption: data.active_collectives === 1 ? 'one home, one community' : `${data.total_collectives} in total`,
      href: '/admin/collectives',
      hue: HUE.green,
    },
    {
      icon: '🌱',
      label: 'Members',
      value: data.member_users,
      caption: `${new Intl.NumberFormat('en-AU').format(data.total_users)} people across the world`,
      href: '/admin/users',
      hue: HUE.blue,
    },
    {
      icon: '🕯️',
      label: 'Creators',
      value: data.creator_users,
      caption: 'building collectives',
      href: '/admin/creators',
      hue: HUE.gold,
    },
    {
      icon: '🌙',
      label: 'Upcoming Gatherings',
      value: data.upcoming_gatherings,
      caption: 'scheduled ahead',
      href: '/admin/collectives',
      hue: HUE.green,
    },
  ]

  return (
    <section>
      <SectionHeader
        title="Life Across Our World"
        subtitle="The shape of Fresh Collective right now."
      />
      <div className="grid gap-4 sm:grid-cols-2">
        {cards.map((c) => (
          <Link
            key={c.label}
            href={c.href}
            className="group flex flex-col justify-between rounded-2xl p-6 transition-all hover:-translate-y-0.5"
            style={{
              background: CARD_BG,
              border: CARD_BORDER,
              boxShadow: CARD_SHADOW,
              minHeight: 168,
            }}
          >
            <div
              className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl text-[20px]"
              style={{ background: c.hue.bg, border: `1px solid ${c.hue.border}` }}
              aria-hidden
            >
              {c.icon}
            </div>
            <div>
              <p className="font-serif text-[38px] leading-none" style={{ color: HUE.ink.text }}>
                {new Intl.NumberFormat('en-AU').format(c.value)}
              </p>
              <p className="mt-3 text-[13.5px] leading-tight" style={{ color: HUE.ink.text }}>
                {c.label}
              </p>
              <p className="mt-1 text-[12.5px] leading-relaxed" style={{ color: HUE.ink.softer }}>
                {c.caption}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Commerce — deliberately quieter than Life. Three lines, one link out.
// ---------------------------------------------------------------------------

function CommerceSection({ data }: { data: MotherWorldOverview }) {
  const fmt = (cents: number) =>
    new Intl.NumberFormat('en-AU', {
      style: 'currency',
      currency: 'AUD',
      minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    }).format(cents / 100)

  const rows = [
    { label: 'Today', value: fmt(data.total_gross_cents_today) },
    { label: 'Past seven days', value: fmt(data.total_gross_cents_7d) },
    {
      label: 'Confirmed transactions',
      value: new Intl.NumberFormat('en-AU').format(data.succeeded_transactions),
    },
  ]

  return (
    <section>
      <SectionHeader
        title="Commerce"
        subtitle="Money flowing through the world."
        action={{ label: 'View Commerce →', href: '/admin/revenue' }}
      />
      <div className="rounded-2xl px-6 py-4" style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}>
        {rows.map((r, i) => (
          <div
            key={r.label}
            className="flex items-baseline justify-between py-3.5"
            style={i > 0 ? { borderTop: HAIRLINE } : undefined}
          >
            <span className="text-[13px]" style={{ color: HUE.ink.softer }}>
              {r.label}
            </span>
            <span className="font-serif text-[22px] leading-none" style={{ color: HUE.ink.text }}>
              {r.value}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Recent Moments — natural-language events. Not audit rows.
// ---------------------------------------------------------------------------

function MomentsSection({ moments }: { moments: MotherWorldMoment[] }) {
  return (
    <section>
      <SectionHeader
        title="Recent Moments"
        subtitle="What's been unfolding across the world."
      />
      <div className="overflow-hidden rounded-2xl" style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}>
        {moments.length === 0 ? (
          <div className="px-7 py-10 text-center">
            <p className="font-serif text-[18px]" style={{ color: HUE.ink.text }}>
              A quiet stretch.
            </p>
            <p className="mt-2 text-[13.5px]" style={SERIF_ITALIC}>
              Moments will appear here as they happen.
            </p>
          </div>
        ) : (
          moments.map((m, i) => (
            <MomentRow key={i} moment={m} first={i === 0} />
          ))
        )}
      </div>
    </section>
  )
}

function MomentRow({ moment, first }: { moment: MotherWorldMoment; first: boolean }) {
  const dotByKind: Record<MotherWorldMoment['kind'], string> = {
    collective:  HUE.green.dot,
    creator:     HUE.gold.dot,
    transaction: HUE.blue.dot,
    signup:      HUE.blue.dot,
    gathering:   HUE.gold.dot,
  }
  const dot = dotByKind[moment.kind] ?? HUE.ink.softer

  const inner = (
    <div
      className="flex items-start gap-4 px-7 py-3.5 transition-colors hover:bg-white/40"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <span
        className="mt-2 inline-block h-2 w-2 shrink-0 rounded-full"
        style={{ background: dot }}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] leading-relaxed" style={{ color: HUE.ink.text }}>
          {moment.message}
        </p>
        <p className="mt-0.5 text-[11.5px]" style={{ color: HUE.ink.softer }}>
          {timeAgo(moment.when)}
        </p>
      </div>
    </div>
  )

  return moment.href ? (
    <Link href={moment.href} className="block">{inner}</Link>
  ) : inner
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diffMs = Date.now() - then
  const mins = Math.round(diffMs / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} minute${mins === 1 ? '' : 's'} ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? '' : 's'} ago`
  const days = Math.round(hrs / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ---------------------------------------------------------------------------
// World Health — grouped Platform / Payments pills.
// ---------------------------------------------------------------------------

function WorldHealthSection({ health }: { health: MotherWorldOverview['world_health'] }) {
  type Pill = { label: string; state: 'ok' | 'waiting' | 'off' | 'info' }

  const platform: Pill[] = [
    { label: health.platform_ok ? 'Online' : 'Offline', state: health.platform_ok ? 'ok' : 'off' },
    {
      label: health.last_backup_at ? `Backup ${timeAgo(health.last_backup_at)}` : 'Backups manual',
      state: health.last_backup_at ? 'ok' : 'waiting',
    },
  ]

  const payments: Pill[] = [
    {
      label: health.stripe_ok
        ? (health.stripe_mode === 'live' ? 'Stripe live' : 'Test mode')
        : 'Stripe off',
      state: health.stripe_ok ? (health.stripe_mode === 'live' ? 'ok' : 'info') : 'off',
    },
    {
      label: health.webhook_configured ? 'Webhooks configured' : 'Webhooks off',
      state: health.webhook_configured ? 'ok' : 'off',
    },
    {
      label: health.standalone_gathering_sales_enabled ? 'Ticket sales on' : 'Ticket sales off',
      state: health.standalone_gathering_sales_enabled ? 'info' : 'ok',
    },
  ]

  return (
    <section>
      <SectionHeader
        title="World Health"
        subtitle="The systems that keep it alive."
      />
      <div className="rounded-2xl px-6 py-5" style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}>
        <HealthGroup title="Platform" pills={platform} />
        <div className="mt-4">
          <HealthGroup title="Payments" pills={payments} />
        </div>
      </div>
    </section>
  )
}

function HealthGroup({
  title, pills,
}: { title: string; pills: { label: string; state: 'ok' | 'waiting' | 'off' | 'info' }[] }) {
  const styleFor = (s: 'ok' | 'waiting' | 'off' | 'info') => {
    const h = s === 'ok' ? HUE.green : s === 'waiting' ? HUE.gold : s === 'info' ? HUE.blue : HUE.coral
    return { background: h.bg, borderColor: h.border, dot: h.dot }
  }

  return (
    <div>
      <p
        className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.18em]"
        style={{ color: HUE.ink.softer }}
      >
        {title}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {pills.map((p, i) => {
          const s = styleFor(p.state)
          return (
            <span
              key={i}
              className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px]"
              style={{ background: s.background, border: `1px solid ${s.borderColor}`, color: HUE.ink.text }}
            >
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: s.dot }}
                aria-hidden
              />
              {p.label}
            </span>
          )
        })}
      </div>
    </div>
  )
}
