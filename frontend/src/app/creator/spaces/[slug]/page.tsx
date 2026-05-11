import { notFound } from 'next/navigation'
import { getCreatorSpace } from '@/lib/serverApi'
import SpaceSettingsForm from './SpaceSettingsForm'

export default async function CreatorSpacePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const space = await getCreatorSpace(slug)
  if (!space) notFound()

  return (
    <div className="max-w-xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">Space Settings</h1>
        <p className="mt-1 text-sm text-slate-400">Name, tagline, visibility, and access.</p>
      </div>
      <SpaceSettingsForm space={space} />
    </div>
  )
}
