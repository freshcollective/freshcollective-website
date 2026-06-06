export default function AdminModerationPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Moderation</h1>
        <p className="mt-1 text-[13px] text-[#64748B]">
          Platform-wide content and community moderation tools.
        </p>
      </div>

      <div
        className="rounded-xl bg-white p-6"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-2 text-[15px] font-semibold text-[#0F172A]">Not yet active</h2>
        <p className="mb-4 text-[13px] text-[#64748B]">
          Moderation tools are not currently connected. No automated content review, flagging, or
          removal workflows are active.
        </p>
        <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[#94A3B8]">Planned features</p>
        <ul className="space-y-1 text-[13px] text-[#64748B]">
          <li>· Review flagged community posts and comments</li>
          <li>· Remove harmful content from any collective</li>
          <li>· Suspend or deactivate member accounts</li>
          <li>· View moderation history and action log</li>
        </ul>
        <p className="mt-4 text-[12px] text-[#94A3B8]">
          For now, content can be managed directly through each collective&rsquo;s Creator Studio.
        </p>
      </div>
    </div>
  )
}
