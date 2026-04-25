import { getSession } from '@/lib/auth/session'
import { prisma } from '@/lib/db'
import Container from '@/components/layout/Container'
import { logout } from '@/lib/auth/actions'

export default async function DashboardPage() {
  const session = await getSession()
  const user = session
    ? await prisma.user.findUnique({
        where: { id: session.userId },
        select: { name: true, email: true, createdAt: true },
      })
    : null

  const firstName = user?.name?.split(' ')[0] ?? 'there'

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Dashboard header */}
      <header
        className="border-b border-border bg-surface py-4"
        style={{ borderTop: '2px solid var(--color-gold-500)' }}
      >
        <Container className="flex items-center justify-between">
          <span className="font-serif text-xl tracking-wide text-navy-900">Fresh Collective</span>
          <div className="flex items-center gap-4">
            <span className="hidden text-sm text-[#4A5568] md:block">{user?.email}</span>
            <form action={logout}>
              <button
                type="submit"
                className="rounded-lg border border-navy-300 px-4 py-2 text-sm font-medium text-navy-700 transition-colors hover:border-navy-500 hover:bg-navy-50"
              >
                Log out
              </button>
            </form>
          </div>
        </Container>
      </header>

      {/* Dashboard content */}
      <main className="flex-1 py-12">
        <Container>
          <div className="mb-10">
            <div className="mb-4 h-px w-6 bg-gold-500" />
            <h1 className="mb-2 font-serif text-4xl text-navy-900">
              Welcome back, {firstName}.
            </h1>
            <p className="text-[#718096]">Your member area is being built. Here&apos;s what&apos;s coming.</p>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            {/* REAL Journey */}
            <div
              className="rounded-xl border border-border bg-surface p-6"
              style={{ boxShadow: 'var(--fc-shadow-sm)' }}
            >
              <div className="mb-3 text-xs font-medium uppercase tracking-widest text-gold-700">
                01 — Foundation
              </div>
              <h2 className="mb-2 font-serif text-xl text-navy-900">REAL Journey</h2>
              <p className="text-sm text-[#718096]">
                A four-phase programme to help you reconnect, expand, act, and live with
                intention.
              </p>
              <div className="mt-4 inline-block rounded-full bg-navy-50 px-3 py-1 text-xs text-navy-500">
                Coming soon
              </div>
            </div>

            {/* The Rooms */}
            <div
              className="rounded-xl border border-border bg-surface p-6"
              style={{ boxShadow: 'var(--fc-shadow-sm)' }}
            >
              <div className="mb-3 text-xs font-medium uppercase tracking-widest text-gold-700">
                02 — Deepening
              </div>
              <h2 className="mb-2 font-serif text-xl text-navy-900">The Rooms</h2>
              <p className="text-sm text-[#718096]">
                Focused pathways to go deeper in the areas that matter most to you.
              </p>
              <div className="mt-4 inline-block rounded-full bg-navy-50 px-3 py-1 text-xs text-navy-500">
                Coming soon
              </div>
            </div>

            {/* The Heart */}
            <div
              className="rounded-xl border border-border bg-surface p-6"
              style={{ boxShadow: 'var(--fc-shadow-sm)' }}
            >
              <div className="mb-3 text-xs font-medium uppercase tracking-widest text-gold-700">
                03 — Community
              </div>
              <h2 className="mb-2 font-serif text-xl text-navy-900">The Heart</h2>
              <p className="text-sm text-[#718096]">
                Monthly live calls and a community of women walking alongside you.
              </p>
              <div className="mt-4 inline-block rounded-full bg-navy-50 px-3 py-1 text-xs text-navy-500">
                Coming soon
              </div>
            </div>
          </div>
        </Container>
      </main>
    </div>
  )
}
