// snake_case → Title Case for enum-like status values. Inlined from the
// removed adminSalesApi module so this shared badge no longer depends on
// the deprecated sales/CRM code path.
function labelStage(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

const STATUS_COLORS: Record<string, string> = {
  // Lead statuses
  prospect: 'bg-slate-100 text-slate-700',
  free_user: 'bg-blue-50 text-blue-700',
  trialing: 'bg-purple-50 text-purple-700',
  active: 'bg-green-50 text-green-700',
  paused: 'bg-yellow-50 text-yellow-700',
  cancelled: 'bg-red-50 text-red-600',
  past_due: 'bg-orange-50 text-orange-700',
  lost: 'bg-slate-100 text-slate-500',
  // Pipeline stages
  new_lead: 'bg-slate-100 text-slate-600',
  contacted: 'bg-blue-50 text-blue-700',
  qualified: 'bg-indigo-50 text-indigo-700',
  invited: 'bg-violet-50 text-violet-700',
  trial_or_free_user: 'bg-cyan-50 text-cyan-700',
  sales_conversation: 'bg-orange-50 text-orange-700',
  checkout_sent: 'bg-amber-50 text-amber-700',
  won: 'bg-green-50 text-green-700',
  nurture: 'bg-pink-50 text-pink-700',
  // Interest levels
  low: 'bg-slate-100 text-slate-500',
  medium: 'bg-blue-50 text-blue-600',
  high: 'bg-teal-50 text-teal-700',
  very_high: 'bg-green-50 text-green-700',
  // Subscription status
}

export default function StatusBadge({ value }: { value: string }) {
  const cls = STATUS_COLORS[value] ?? 'bg-slate-100 text-slate-600'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {labelStage(value)}
    </span>
  )
}
