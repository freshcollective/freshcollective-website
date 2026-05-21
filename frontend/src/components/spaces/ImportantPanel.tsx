interface Props {
  startTitle?: string | null
  startBody?: string | null
  focusTitle?: string | null
  focusBody?: string | null
  linksTitle?: string | null
  linksBody?: string | null
}

const DEFAULTS = {
  startTitle: 'Start here',
  startBody: 'Your guide has added a welcome message or first step here.',
  focusTitle: 'Upcoming focus',
  focusBody: 'A weekly theme or prompt will appear here.',
  linksTitle: 'Helpful links',
  linksBody: 'Key resources and links will appear here.',
}

export default function ImportantPanel({
  startTitle,
  startBody,
  focusTitle,
  focusBody,
  linksTitle,
  linksBody,
}: Props) {
  const s = {
    startTitle: startTitle || DEFAULTS.startTitle,
    startBody:  startBody  || DEFAULTS.startBody,
    focusTitle: focusTitle || DEFAULTS.focusTitle,
    focusBody:  focusBody  || DEFAULTS.focusBody,
    linksTitle: linksTitle || DEFAULTS.linksTitle,
    linksBody:  linksBody  || DEFAULTS.linksBody,
  }

  return (
    <div
      className="rounded-2xl bg-white px-5 py-6"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      <div
        className="mb-3 h-[2px] w-5 rounded-full"
        style={{ background: 'linear-gradient(90deg, #BF9830 0%, transparent 100%)' }}
      />
      <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        Important
      </p>

      <div className="flex flex-col gap-4">
        <div>
          <p className="mb-1 text-[13px] font-semibold text-navy-900">{s.startTitle}</p>
          <p className="text-[12px] leading-relaxed text-slate-500">{s.startBody}</p>
        </div>
        <div className="h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />
        <div>
          <p className="mb-1 text-[13px] font-semibold text-navy-900">{s.focusTitle}</p>
          <p className="text-[12px] leading-relaxed text-slate-500">{s.focusBody}</p>
        </div>
        <div className="h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />
        <div>
          <p className="mb-1 text-[13px] font-semibold text-navy-900">{s.linksTitle}</p>
          <p className="text-[12px] leading-relaxed text-slate-500">{s.linksBody}</p>
        </div>
      </div>
    </div>
  )
}
