const TYPE_STYLES: Record<string, string> = {
  announcement: 'bg-teal-900/10 text-teal-800',
  prompt:       'bg-teal-50 text-teal-700',
  reflection:   'bg-navy-50 text-navy-600',
  discussion:   'bg-slate-100 text-slate-600',
}

const TYPE_LABEL: Record<string, string> = {
  announcement: 'Announcement',
  prompt:       'Prompt',
  reflection:   'Reflection',
  discussion:   'Discussion',
}

export default function PostTypeTag({ type }: { type: string }) {
  const styles = TYPE_STYLES[type] ?? TYPE_STYLES.discussion
  const label = TYPE_LABEL[type] ?? type
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${styles}`}>
      {label}
    </span>
  )
}
