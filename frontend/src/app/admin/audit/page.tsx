export default function AdminAuditPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Audit Logs</h1>
        <p className="mt-1 text-[13px] text-[#64748B]">
          Record of significant admin actions across the platform.
        </p>
      </div>

      <div
        className="rounded-xl bg-white p-6"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-2 text-[15px] font-semibold text-[#0F172A]">Not yet active</h2>
        <p className="mb-4 text-[13px] text-[#64748B]">
          Audit logging is not currently connected. No admin actions are being automatically recorded
          in an audit trail.
        </p>
        <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[#94A3B8]">Planned audit events</p>
        <ul className="space-y-1 text-[13px] text-[#64748B]">
          <li>· User role changes</li>
          <li>· Creator plan changes</li>
          <li>· Manual payment records created</li>
          <li>· Access request approvals and declines</li>
          <li>· Collective status changes</li>
          <li>· Admin account login events</li>
        </ul>
        <p className="mt-4 text-[12px] text-[#94A3B8]">
          Some actions (e.g. manual payment records) are visible in the Payments page until
          a dedicated audit trail is implemented.
        </p>
      </div>
    </div>
  )
}
