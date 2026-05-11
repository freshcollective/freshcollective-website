import Image from 'next/image'

const SIZE_CLASSES = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-xs',
  lg: 'h-14 w-14 text-sm',
  xl: 'h-20 w-20 text-base',
}

const COLORS = [
  'bg-teal-100 text-teal-700',
  'bg-navy-100 text-navy-700',
  'bg-gold-100 text-gold-700',
  'bg-slate-100 text-slate-600',
]

function colorForName(name: string): string {
  const hash = name.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0)
  return COLORS[hash % COLORS.length]
}

function initialsFor(name: string): string {
  return name
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
    || '?'
}

interface AvatarProps {
  name: string
  avatarUrl?: string | null
  size?: keyof typeof SIZE_CLASSES
}

export default function Avatar({ name, avatarUrl, size = 'md' }: AvatarProps) {
  const sizeClass = SIZE_CLASSES[size]
  const colorClass = colorForName(name)
  const initials = initialsFor(name)

  if (avatarUrl) {
    return (
      <div className={`${sizeClass} shrink-0 overflow-hidden rounded-full`}>
        <Image
          src={avatarUrl}
          alt={name}
          width={80}
          height={80}
          className="h-full w-full object-cover"
        />
      </div>
    )
  }

  return (
    <div
      className={`${sizeClass} ${colorClass} flex shrink-0 items-center justify-center rounded-full font-semibold`}
    >
      {initials}
    </div>
  )
}
