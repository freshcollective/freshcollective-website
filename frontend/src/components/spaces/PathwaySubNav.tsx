import Link from 'next/link'

interface Props {
  spaceSlug: string
  pathwaySlug: string
  activeTab: 'about' | 'pathway'
}

export default function PathwaySubNav({ spaceSlug, pathwaySlug, activeTab }: Props) {
  const aboutHref = `/spaces/${spaceSlug}/pathways/${pathwaySlug}/about`
  const overviewHref = `/spaces/${spaceSlug}/pathways/${pathwaySlug}`

  return (
    <div className="flex w-fit items-center gap-1 rounded-xl border border-border bg-white p-1 shadow-sm">
      <Link
        href={aboutHref}
        className={[
          'rounded-lg px-4 py-2 text-[13px] font-medium transition-colors',
          activeTab === 'about'
            ? 'bg-teal-50 text-teal-700'
            : 'text-slate-500 hover:bg-slate-50 hover:text-navy-900',
        ].join(' ')}
      >
        About
      </Link>
      <Link
        href={overviewHref}
        className={[
          'rounded-lg px-4 py-2 text-[13px] font-medium transition-colors',
          activeTab === 'pathway'
            ? 'bg-teal-50 text-teal-700'
            : 'text-slate-500 hover:bg-slate-50 hover:text-navy-900',
        ].join(' ')}
      >
        Pathway
      </Link>
    </div>
  )
}
