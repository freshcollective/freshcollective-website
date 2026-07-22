import Link from 'next/link'

export default function AdminSettingsPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">World Settings</h1>
        <p className="mt-1 text-[13px] text-[#000000]">
          Shared settings that shape the experience of the entire world.
        </p>
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Link
          href="/admin/settings/artwork"
          className="group block rounded-xl bg-white p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
          style={{ border: '1px solid #E2E8F0' }}
        >
          <h2 className="text-[15px] font-semibold text-[#0F172A]">World Artwork</h2>
          <p className="mt-1 text-[13px] text-[#000000]">
            Manage the shared imagery that gives Fresh Collective its visual identity.
          </p>
          <p className="mt-3 text-[12px] font-semibold" style={{ color: '#38A09E' }}>
            Manage artwork →
          </p>
        </Link>
      </div>

      <div
        className="rounded-xl bg-white p-6"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-2 text-[15px] font-semibold text-[#0F172A]">Not yet active</h2>
        <p className="mb-4 text-[13px] text-[#000000]">
          Platform configuration controls are not currently active. No global settings will take
          effect from this page.
        </p>
        <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[#000000]">Planned settings</p>
        <ul className="space-y-1 text-[13px] text-[#000000]">
          <li>· Platform name, branding, and domain</li>
          <li>· Default onboarding flow and welcome copy</li>
          <li>· Email notification and digest settings</li>
          <li>· Feature flags and access controls</li>
          <li>· Stripe and payment gateway configuration</li>
        </ul>
        <p className="mt-4 text-[12px] text-[#000000]">
          Configuration changes currently require a code deployment or database update.
        </p>
      </div>
    </div>
  )
}
