import Link from 'next/link'
import SettingsNav from '@/components/settings/SettingsNav'

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4 md:px-10">
          <Link href="/dashboard" className="font-serif text-lg text-navy-900 hover:text-teal-600">
            Fresh Collective
          </Link>
          <Link href="/dashboard" className="text-sm text-slate-500 hover:text-navy-700">
            ← Dashboard
          </Link>
        </div>
      </header>

      <main className="flex-1 py-10">
        <div className="mx-auto max-w-4xl px-6 md:px-10">
          <div className="mb-8">
            <div className="mb-2 h-px w-6 bg-gold-500" />
            <h1 className="font-serif text-2xl text-navy-900">Account Settings</h1>
          </div>

          <div className="md:grid md:grid-cols-[200px_1fr] md:gap-12">
            <aside>
              <SettingsNav />
            </aside>
            <div className="min-w-0">{children}</div>
          </div>
        </div>
      </main>
    </div>
  )
}
