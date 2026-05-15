const TYPE_STYLES: Record<string, string> = {
  prompt:      'bg-teal-50 text-teal-700',
  reflection:  'bg-navy-50 text-navy-600',
  discussion:  'bg-slate-100 text-slate-600',
}

const TYPE_LABEL: Record<string, string> = {
  announcement: 'Announcement',
  prompt:       'Prompt',
  reflection:   'Reflection',
  discussion:   'Discussion',
}

export default function PostTypeTag({ type }: { type: string }) {
  const label = TYPE_LABEL[type] ?? type

  if (type === 'announcement') {
    return (
      <span
        className="inline-block rounded-full px-2.5 py-0.5 text-xs font-medium"
        style={{ background: '#FFF6D8', color: '#7A5F10' }}
      >
        {label}
      </span>
    )
  }

  const styles = TYPE_STYLES[type] ?? TYPE_STYLES.discussion
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${styles}`}>
      {label}
    </span>
  )
}
