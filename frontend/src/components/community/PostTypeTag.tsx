/**
 * PostTypeTag — a subtle chip that names the kind of conversation a
 * post is inviting. Kept small and consistent across the feed; the
 * only variation between types is icon, label, and a low-saturation
 * colour so the feed still feels calm.
 */

interface TypeMeta {
  label: string
  icon: string
  bg: string
  color: string
}

const TYPE_META: Record<string, TypeMeta> = {
  reflection:   { label: 'Reflection',   icon: '❁', bg: 'rgba(122,90,157,0.10)',  color: '#5C4577' },
  question:     { label: 'Question',     icon: '?', bg: 'rgba(56,160,158,0.10)',  color: '#0f766e' },
  poll:         { label: 'Poll',         icon: '▤', bg: 'rgba(214,177,63,0.14)',  color: '#8A6A15' },
  announcement: { label: 'Announcement', icon: '✦', bg: '#FFF6D8',                color: '#7A5F10' },
  celebration:  { label: 'Celebration',  icon: '✿', bg: 'rgba(232,86,105,0.10)',  color: '#A83048' },
  // Enum value `share` is displayed as "Discussion" so the visible
  // vocabulary reads more naturally. Backend enum stays unchanged for
  // rollback safety and to keep existing rows valid.
  share:        { label: 'Discussion',   icon: '☷', bg: 'rgba(56,160,158,0.08)',  color: '#0f766e' },
  // Legacy — kept so historical posts still render a chip.
  prompt:       { label: 'Prompt',       icon: '·', bg: 'rgba(56,160,158,0.08)',  color: '#0f766e' },
  discussion:   { label: 'Discussion',   icon: '·', bg: 'rgba(0,0,0,0.05)',       color: '#475569' },
}

export default function PostTypeTag({ type }: { type: string }) {
  const meta = TYPE_META[type] ?? TYPE_META.reflection
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium"
      style={{ background: meta.bg, color: meta.color }}
    >
      <span aria-hidden="true">{meta.icon}</span>
      <span>{meta.label}</span>
    </span>
  )
}

/** Ordered list of user-choosable post types for the composer. */
export const POST_TYPE_OPTIONS: ReadonlyArray<{ value: string; label: string; icon: string }> = [
  { value: 'reflection',   label: 'Reflection',   icon: '❁' },
  { value: 'question',     label: 'Question',     icon: '?' },
  { value: 'poll',         label: 'Poll',         icon: '▤' },
  { value: 'announcement', label: 'Announcement', icon: '✦' },
  { value: 'celebration',  label: 'Celebration',  icon: '✿' },
  { value: 'share',        label: 'Discussion',   icon: '☷' },
]

export const POST_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(TYPE_META).map(([k, v]) => [k, v.label]),
)
