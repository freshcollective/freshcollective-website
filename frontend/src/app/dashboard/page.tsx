import { cookies } from 'next/headers'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'

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

export default async function DashboardPage() {
  const user = await getUser()
  const firstName = user?.name?.split(' ')[0] ?? 'there'

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header
        className="border-b border-border bg-surface py-4"
        style={{ borderTop: '2px solid var(--color-gold-500)' }}
      >
        <Container className="flex items-center justify-between">
          <span className="font-serif text-xl tracking-wide text-navy-900">Fresh Collective</span>
          <div className="flex items-center gap-4">
            <span className="hidden text-sm text-[#4A5568] md:block">{user?.email}</span>
            <LogoutButton className="rounded-lg border border-navy-300 px-4 py-2 text-sm font-medium text-navy-700 transition-colors hover:border-navy-500 hover:bg-navy-50" />
          </div>
        </Container>
      </header>

      <main className="flex-1 py-12">
        <Container>
          <div className="mb-10">
            <div className="mb-4 h-px w-6 bg-gold-500" />
            <h1 className="mb-2 font-serif text-4xl text-navy-900">Welcome back, {firstName}.</h1>
            <p className="text-[#718096]">Your member area is being built. Here&apos;s what&apos;s coming.</p>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            {[
              { num: '01', label: 'Foundation', title: 'REAL Journey', desc: 'The foundational pathway. Four phases — Recognise, Explore, Align, Lead — to help you reconnect and move forward with intention.' },
              { num: '02', label: 'Pathways', title: 'The Rooms', desc: 'Structured pathways to go deeper. Growth, Transformation, and Essence — each with guided steps and reflection.' },
              { num: '03', label: 'Community & Events', title: 'Fresh Collective Space', desc: 'Monthly live calls, community prompts, and a space of women walking alongside you.' },
            ].map(({ num, label, title, desc }) => (
              <div key={num} className="rounded-xl border border-border bg-surface p-6" style={{ boxShadow: 'var(--fc-shadow-sm)' }}>
                <div className="mb-3 text-xs font-medium uppercase tracking-widest text-gold-700">{num} — {label}</div>
                <h2 className="mb-2 font-serif text-xl text-navy-900">{title}</h2>
                <p className="text-sm text-[#718096]">{desc}</p>
                <div className="mt-4 inline-block rounded-full bg-navy-50 px-3 py-1 text-xs text-navy-500">Coming soon</div>
              </div>
            ))}
          </div>
        </Container>
      </main>
    </div>
  )
}
