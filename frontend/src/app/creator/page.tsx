import Link from 'next/link'
import { getCreatorSpaces } from '@/lib/serverApi'
import type { SpaceSummary } from '@/types/platform'

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: 'bg-teal-400',
    draft: 'bg-slate-300',
    archived: 'bg-red-300',
  }
  return <span className={`inline-block h-2 w-2 rounded-full ${colors[status] ?? 'bg-slate-300'}`} />
}

function StudioLink({ href, label, muted }: { href: string; label: string; muted?: boolean }) {
  return (
    <Link
      href={href}
      className={[
        'rounded-lg border px-4 py-2 text-sm font-medium transition-colors',
        muted
          ? 'border-border text-slate-400 hover:border-slate-300 hover:text-navy-700'
          : 'border-navy-200 text-navy-700 hover:border-navy-400 hover:bg-navy-50',
      ].join(' ')}
    >
      {label}
    </Link>
  )
}

export default async function CreatorPage() {
  const spaces: SpaceSummary[] = await getCreatorSpaces()

  return (
    <div className="mx-auto max-w-4xl px-6 py-12 md:px-10">
      <div className="mb-10">
        <div className="mb-2 h-px w-8 bg-gold-400" />
        <h1 className="mb-1 font-serif text-3xl text-navy-900">Your Spaces</h1>
        <p className="text-sm text-slate-500">
          Select a Space to manage its content and community.
        </p>
      </div>

      {spaces.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface px-8 py-10 text-center">
          <p className="font-serif text-xl text-navy-700">No spaces yet.</p>
          <p className="mt-2 text-sm text-slate-400">Spaces are created by the platform administrator.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {spaces.map((space) => (
            <div key={space.id} className="rounded-xl border border-border bg-surface px-6 py-5">
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <div className="mb-1 flex items-center gap-2">
                    <StatusDot status={space.status} />
                    <h2 className="font-serif text-xl text-navy-900">{space.name}</h2>
                  </div>
                  {space.tagline && <p className="text-sm text-slate-400">{space.tagline}</p>}
                </div>
                <Link
                  href={`/spaces/${space.slug}`}
                  className="shrink-0 text-xs text-teal-600 hover:underline"
                  target="_blank"
                >
                  View live ↗
                </Link>
              </div>
              <div className="flex flex-wrap gap-2">
                <StudioLink href={`/creator/spaces/${space.slug}/pathways`} label="Pathways" />
                <StudioLink href={`/creator/spaces/${space.slug}/events`} label="Events" />
                <StudioLink href={`/creator/spaces/${space.slug}/community`} label="Community" />
                <StudioLink href={`/creator/spaces/${space.slug}`} label="Settings" muted />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
