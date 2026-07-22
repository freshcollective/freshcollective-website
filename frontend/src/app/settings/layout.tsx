import Link from 'next/link'
import SettingsNav from '@/components/settings/SettingsNav'

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-white">
      <header className="border-b border-border bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4 md:px-10">
          <Link href="/dashboard" className="font-serif text-lg text-navy-900 hover:text-teal-600">
            Fresh Collective
          </Link>
          <Link href="/dashboard" className="text-sm text-black hover:text-navy-700">
            ← Your World
          </Link>
        </div>
      </header>

      <main className="flex-1 py-10">
        <div className="mx-auto max-w-4xl px-6 md:px-10">

          {/* Heading */}
          <div className="mb-10">
            <div
              className="mb-3 h-[2px] w-8 rounded-full"
              style={{ background: 'linear-gradient(90deg, #BF9830 0%, transparent 100%)' }}
            />
            <h1 className="text-2xl font-semibold leading-snug">
              <span
                style={{
                  background: 'linear-gradient(90deg, #38A09E 0%, #071824 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                }}
                className="inline-block"
              >
                Account Settings
              </span>
            </h1>
          </div>

          <div className="md:grid md:grid-cols-[180px_1fr] md:gap-12">
            <aside>
              <SettingsNav />
            </aside>
            <div className="min-w-0 pt-8 md:pt-0">{children}</div>
          </div>
        </div>
      </main>
    </div>
  )
}
