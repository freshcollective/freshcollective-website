export default function AdminSettingsPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Platform Settings</h1>
        <p className="mt-1 text-[13px] text-[#64748B]">
          Global configuration for Fresh Collective.
        </p>
      </div>

      <div
        className="rounded-xl bg-white p-6"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-2 text-[15px] font-semibold text-[#0F172A]">Not yet active</h2>
        <p className="mb-4 text-[13px] text-[#64748B]">
          Platform configuration controls are not currently active. No global settings will take
          effect from this page.
        </p>
        <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[#94A3B8]">Planned settings</p>
        <ul className="space-y-1 text-[13px] text-[#64748B]">
          <li>· Platform name, branding, and domain</li>
          <li>· Default onboarding flow and welcome copy</li>
          <li>· Email notification and digest settings</li>
          <li>· Feature flags and access controls</li>
          <li>· Stripe and payment gateway configuration</li>
        </ul>
        <p className="mt-4 text-[12px] text-[#94A3B8]">
          Configuration changes currently require a code deployment or database update.
        </p>
      </div>
    </div>
  )
}
