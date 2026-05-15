'use client'

import { useRouter } from 'next/navigation'
import type { SpaceSummary } from '@/types/platform'

export default function CollectiveRow({
  space,
  isActive,
}: {
  space: SpaceSummary
  isActive: boolean
}) {
  const router = useRouter()

  function open() {
    document.cookie = `fc_creator_space=${space.slug}; path=/; max-age=86400`
    router.push('/creator-studio/settings')
    router.refresh()
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && open()}
      className="group flex cursor-pointer items-center gap-4 rounded-xl border p-4 transition-all hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
      style={{
        borderColor: isActive ? 'rgba(56,160,158,0.30)' : '#e2e8f0',
        background: isActive ? 'rgba(56,160,158,0.04)' : 'white',
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget
        el.style.borderColor = 'rgba(56,160,158,0.40)'
        el.style.background = isActive ? 'rgba(56,160,158,0.07)' : 'rgba(56,160,158,0.03)'
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget
        el.style.borderColor = isActive ? 'rgba(56,160,158,0.30)' : '#e2e8f0'
        el.style.background = isActive ? 'rgba(56,160,158,0.04)' : 'white'
      }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[14px] font-medium text-navy-900 transition-colors group-hover:text-teal-700">
            {space.name}
          </p>
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
            style={{
              background: space.status === 'active' ? 'rgba(56,160,158,0.10)' : 'rgba(0,0,0,0.05)',
              color: space.status === 'active' ? '#38A09E' : '#94a3b8',
            }}
          >
            {space.status}
          </span>
          {isActive && (
            <span className="text-[11px] font-medium text-teal-500">Active</span>
          )}
        </div>
        {space.tagline && (
          <p className="mt-0.5 truncate text-[13px] text-slate-500">{space.tagline}</p>
        )}
      </div>
      <span className="shrink-0 text-[13px] font-medium text-teal-600 transition-colors group-hover:text-teal-700">
        Manage →
      </span>
    </div>
  )
}
