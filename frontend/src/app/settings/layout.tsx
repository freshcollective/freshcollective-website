import SettingsNav from '@/components/settings/SettingsNav'
import WorldShell from '@/components/layout/WorldShell'
import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'

export default async function SettingsLayout({ children }: { children: React.ReactNode }) {
  // Previously relied on the proxy middleware alone (see
  // ``src/proxy.ts``) — but middleware only verifies the JWT signature
  // and cannot tell whether the User row still exists. The shared
  // guard closes that gap for /settings the same way it does for
  // /dashboard.
  await requireAuthenticatedUser()
  return (
    <WorldShell>
      <div className="min-h-screen bg-white">
        <div className="mx-auto max-w-4xl px-6 py-10 md:px-10">

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
      </div>
    </WorldShell>
  )
}
