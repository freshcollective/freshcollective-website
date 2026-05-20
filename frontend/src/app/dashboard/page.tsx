import { cookies } from 'next/headers'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import Avatar from '@/components/ui/Avatar'
import { GoldLabel, PillTag } from '@/components/ui/BrandLabel'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import { getMyMemberships, getPublicSpaces } from '@/lib/serverApi'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import type { SpaceMembership, PublicSpaceCard } from '@/types/platform'

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

async function getUser(): Promise<User | null> {
  const cookieStore = await cookies()
  const session = cookieStore.get(SESSION_COOKIE)
  if (!session) return null
  try {
    const res = await fetch(apiUrl('/api/auth/me'), {
      headers: { Cookie: `${SESSION_COOKIE}=${session.value}` },
      cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

const CARD_BORDER = '1px solid rgba(0,0,0,0.07)'
const CARD_SHADOW = '0 1px 3px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.05)'

export default async function DashboardPage() {
  const [user, memberships, publicSpaces]: [
    User | null,
    SpaceMembership[],
    PublicSpaceCard[],
  ] = await Promise.all([
    getUser(),
    getMyMemberships(),
    getPublicSpaces(),
  ])

  const firstName = user?.name?.split(' ')[0] ?? 'there'
  const displayName = user?.name ?? firstName
  const isCreatorOrAdmin = user?.role === 'creator' || user?.role === 'admin'

  const activeMemberships = memberships.filter((m) => m.status === 'active')

  // Lookup cover images, taglines, and counts from public space data
  const spaceCardBySlug = new Map(publicSpaces.map((s) => [s.slug, s]))

  return (
    <div className="flex min-h-screen flex-col" style={{ background: '#FAFAF8' }}>

      {/* ── Top navigation ── */}
      <header className="border-b border-slate-100 bg-white py-3.5" style={{ borderTop: '2px solid #38A09E' }}>
        <Container className="flex items-center justify-between">
          <span className="font-serif text-xl text-navy-900">Fresh Collective</span>
          <div className="flex items-center gap-3">
            <Link
              href="/settings"
              className="text-sm text-slate-500 transition-colors hover:text-navy-700"
            >
              Settings
            </Link>
            <Link
              href="/settings/profile"
              className="flex items-center rounded-lg px-1.5 py-1 transition-colors hover:bg-slate-50"
              aria-label="Your profile"
            >
              <Avatar name={displayName} size="sm" />
            </Link>
            <LogoutButton className="text-sm text-slate-400 transition-colors hover:text-slate-600" />
          </div>
        </Container>
      </header>

      <main className="flex-1 py-8">
        <Container>

          {/* ── Welcome card ── */}
          <div
            className="mb-8 overflow-hidden rounded-2xl bg-white px-6 py-5 md:px-8 md:py-6"
            style={{
              boxShadow: '0 1px 4px rgba(0,0,0,0.04), 0 4px 20px rgba(0,0,0,0.06)',
              border: '1px solid rgba(0,0,0,0.06)',
            }}
          >
            <div
              className="mb-2 h-[2px] w-5 rounded-full"
              style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
            />
            <h1
              className="text-3xl md:text-4xl"
              style={{
                background: 'linear-gradient(90deg, #071824 0%, #0F5E5C 55%, #38A09E 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              Welcome back, {firstName}.
            </h1>
            <p className="mt-1.5 text-[14px] text-slate-500">
              Ready to continue where you left off?
            </p>
          </div>

          {/* ── Collectives you belong to ── */}
          <section className="mb-8">
            <GoldLabel className="mb-4">Collectives you belong to</GoldLabel>

            {activeMemberships.length > 0 ? (
              <>
                {/* Collective cards grid */}
                <div className={[
                  'mb-5 grid gap-4',
                  activeMemberships.length > 1 ? 'sm:grid-cols-2' : '',
                ].join(' ')}>
                  {activeMemberships.map((m) => {
                    const spaceCard = spaceCardBySlug.get(m.space_slug)
                    const cs = getCollectiveCoverStyle(m.space_slug)
                    const resolvedImageUrl = resolveMediaUrl(spaceCard?.cover_image_url ?? null)
                    const hasImage = Boolean(resolvedImageUrl)

                    return (
                      <Link
                        key={m.space_id}
                        href={`/spaces/${m.space_slug}`}
                        className="group block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-xl"
                        style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
                      >
                        {/* Cover */}
                        <div className="relative overflow-hidden" style={{ height: '168px' }}>
                          {hasImage ? (
                            <>
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={resolvedImageUrl!}
                                alt={m.space_name}
                                className="h-full w-full object-cover"
                              />
                              <div
                                className="absolute inset-0"
                                style={{
                                  background:
                                    'linear-gradient(to top, rgba(7,24,36,0.78) 0%, rgba(7,24,36,0.20) 50%, transparent 80%)',
                                }}
                              />
                            </>
                          ) : (
                            <div
                              className="absolute inset-0"
                              style={{
                                background: cs.background,
                                backgroundSize: cs.backgroundSize ?? 'auto',
                              }}
                            />
                          )}

                          {/* Name + tagline overlay */}
                          <div className="absolute inset-x-0 bottom-0 p-4">
                            <p
                              className="mb-0.5 text-[9px] font-bold uppercase tracking-[0.20em]"
                              style={{ color: hasImage ? 'rgba(255,255,255,0.60)' : cs.labelColor }}
                            >
                              Collective
                            </p>
                            <p
                              className="font-serif text-xl leading-tight transition-opacity group-hover:opacity-90"
                              style={{ color: hasImage ? '#FFFFFF' : cs.titleColor }}
                            >
                              {m.space_name}
                            </p>
                            {spaceCard?.tagline && (
                              <p
                                className="mt-0.5 line-clamp-1 text-[12px]"
                                style={{ color: hasImage ? 'rgba(255,255,255,0.68)' : cs.labelColor }}
                              >
                                {spaceCard.tagline}
                              </p>
                            )}
                          </div>

                          {/* Hover badge */}
                          <span
                            className="absolute right-3 top-3 rounded-lg border px-3 py-1.5 text-[12px] font-semibold opacity-0 transition-all group-hover:opacity-100"
                            style={{
                              color: '#FFFFFF',
                              borderColor: 'rgba(255,255,255,0.35)',
                              background: 'rgba(0,0,0,0.32)',
                            }}
                          >
                            Open →
                          </span>
                        </div>

                        {/* Footer — counts + CTA */}
                        <div className="flex items-center justify-between gap-3 bg-white px-4 py-2.5">
                          <div className="flex items-center gap-3 text-[12px] text-slate-400">
                            {spaceCard?.pathway_count ? (
                              <span>
                                {spaceCard.pathway_count}{' '}
                                {spaceCard.pathway_count === 1 ? 'pathway' : 'pathways'}
                              </span>
                            ) : null}
                            {spaceCard?.member_count ? (
                              <span>
                                {spaceCard.member_count}{' '}
                                {spaceCard.member_count === 1 ? 'member' : 'members'}
                              </span>
                            ) : null}
                          </div>
                          <span className="shrink-0 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                            Open collective →
                          </span>
                        </div>
                      </Link>
                    )
                  })}
                </div>

                {/* Explore CTA — navy feature card, below own collectives */}
                <Link
                  href="/dashboard/explore"
                  className="group block overflow-hidden rounded-2xl px-6 py-6 transition-all hover:-translate-y-0.5 hover:shadow-xl"
                  style={{
                    background: '#071824',
                    border: '1px solid rgba(66,199,198,0.10)',
                    boxShadow: '0 8px 40px rgba(7,24,36,0.28), 0 2px 8px rgba(0,0,0,0.14)',
                  }}
                >
                  <div
                    className="mb-3 h-[2px] w-5 rounded-full"
                    style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
                  />
                  <h3
                    className="font-serif text-xl leading-snug transition-opacity group-hover:opacity-80 md:text-2xl"
                    style={{
                      background: 'linear-gradient(90deg, #55D7D2 0%, #BDF7F5 35%, #FFFFFF 75%)',
                      WebkitBackgroundClip: 'text',
                      WebkitTextFillColor: 'transparent',
                      backgroundClip: 'text',
                    }}
                  >
                    Explore collectives
                  </h3>
                  <p className="mt-1.5 text-[13px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.72)' }}>
                    Find other guided spaces and communities to join.
                  </p>
                  <span
                    className="mt-5 inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
                    style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                  >
                    Browse collectives →
                  </span>
                </Link>
              </>
            ) : (
              /* Empty state — no memberships */
              <div
                className="rounded-2xl p-8 text-center"
                style={{ background: '#FFFFFF', border: CARD_BORDER, boxShadow: CARD_SHADOW }}
              >
                <p className="font-serif text-[17px] text-navy-900">
                  You&apos;re not part of any collectives yet.
                </p>
                <p className="mt-2 text-[13px] leading-relaxed text-slate-500">
                  Collectives are guided spaces where you learn, reflect, and connect with others.
                </p>
                <Link
                  href="/dashboard/explore"
                  className="mt-5 inline-flex items-center gap-1.5 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                  style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                >
                  Explore collectives →
                </Link>
              </div>
            )}
          </section>

          {/* ── Creator tools ── */}
          {isCreatorOrAdmin && (
            <section className="mb-8 max-w-2xl">
              <GoldLabel className="mb-4">Creator tools</GoldLabel>
              <Link
                href="/creator-studio"
                className="group block overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5 hover:shadow-md"
                style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
              >
                <div className="px-6 py-6">
                  <div className="mb-3">
                    <PillTag>Creator</PillTag>
                  </div>
                  <h3 className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                    Creator Studio
                  </h3>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">
                    Build and manage your collectives, pathways, gatherings, and people.
                  </p>
                  <span
                    className="mt-4 inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
                    style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                  >
                    Open Studio →
                  </span>
                </div>
              </Link>
            </section>
          )}

          {/* ── Footer ── */}
          <div className="border-t border-slate-100 pt-6">
            <LogoutButton className="text-xs text-slate-400 transition-colors hover:text-slate-600" />
          </div>

        </Container>
      </main>
    </div>
  )
}
