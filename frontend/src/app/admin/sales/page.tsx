'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { salesApi, type SalesSummary, fmtDate } from '@/lib/adminSalesApi'
import StatusBadge from '@/components/admin/StatusBadge'

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string | number
  sub?: string
  accent?: boolean
}) {
  return (
    <div
      className="rounded-xl bg-white p-4"
      style={{ border: '1px solid #E2E8F0' }}
    >
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
        {label}
      </p>
      <p
        className={`text-[1.5rem] font-bold leading-none ${accent ? 'text-teal-600' : 'text-[#0F172A]'}`}
      >
        {value}
      </p>
      {sub && <p className="mt-1 text-[12px] text-[#94A3B8]">{sub}</p>}
    </div>
  )
}

export default function SalesSummaryPage() {
  const [data, setData] = useState<SalesSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    salesApi.getSummary()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[14px] text-[#64748B]">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
        Loading summary…
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
        {error}
      </div>
    )
  }

  if (!data) return null

  return (
    <div>
      <h1 className="mb-6 text-[1.5rem] font-bold text-[#0F172A]">Sales Overview</h1>

      {/* Key metrics */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <MetricCard label="Total Leads" value={data.total_leads} />
        <MetricCard label="Open Opps" value={data.open_opportunities} />
        <MetricCard label="Won" value={data.won_opportunities} accent />
        <MetricCard label="Lost" value={data.lost_opportunities} />
        <MetricCard label="Active Subscriptions" value={data.active_subscriptions} />
        <MetricCard label="MRR" value={data.mrr_display} accent />
        <MetricCard label="Pipeline Value" value={data.pipeline_value_display} />
        <MetricCard
          label="Tasks"
          value={data.open_tasks}
          sub={data.overdue_tasks > 0 ? `${data.overdue_tasks} overdue` : undefined}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Leads by stage */}
        <div className="rounded-xl bg-white p-4" style={{ border: '1px solid #E2E8F0' }}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[13px] font-semibold text-[#0F172A]">Leads by Stage</h2>
            <Link href="/admin/sales/leads" className="text-[12px] text-teal-600 hover:underline">
              View all →
            </Link>
          </div>
          {data.leads_by_stage.length === 0 ? (
            <p className="text-[13px] text-[#94A3B8]">No leads yet.</p>
          ) : (
            <div className="space-y-1.5">
              {data.leads_by_stage.map(({ stage, count }) => (
                <div key={stage} className="flex items-center justify-between">
                  <StatusBadge value={stage} />
                  <span className="text-[13px] font-semibold text-[#0F172A]">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Opportunities by stage */}
        <div className="rounded-xl bg-white p-4" style={{ border: '1px solid #E2E8F0' }}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[13px] font-semibold text-[#0F172A]">Opportunities by Stage</h2>
            <Link href="/admin/sales/opportunities" className="text-[12px] text-teal-600 hover:underline">
              View all →
            </Link>
          </div>
          {data.opportunities_by_stage.length === 0 ? (
            <p className="text-[13px] text-[#94A3B8]">No opportunities yet.</p>
          ) : (
            <div className="space-y-1.5">
              {data.opportunities_by_stage.map(({ stage, count }) => (
                <div key={stage} className="flex items-center justify-between">
                  <StatusBadge value={stage} />
                  <span className="text-[13px] font-semibold text-[#0F172A]">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Upcoming tasks */}
        <div className="rounded-xl bg-white p-4" style={{ border: '1px solid #E2E8F0' }}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[13px] font-semibold text-[#0F172A]">Upcoming Tasks</h2>
            <Link href="/admin/sales/tasks" className="text-[12px] text-teal-600 hover:underline">
              View all →
            </Link>
          </div>
          {data.upcoming_tasks.length === 0 ? (
            <p className="text-[13px] text-[#94A3B8]">No upcoming tasks.</p>
          ) : (
            <div className="space-y-2">
              {data.upcoming_tasks.map((t) => (
                <div key={t.id} className="rounded-lg p-2" style={{ background: '#F8F9FA' }}>
                  <p className="text-[13px] font-medium text-[#0F172A] leading-snug">{t.title}</p>
                  <p className="mt-0.5 text-[11px] text-[#94A3B8]">
                    {t.due_at ? `Due ${fmtDate(t.due_at)}` : 'No due date'}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
