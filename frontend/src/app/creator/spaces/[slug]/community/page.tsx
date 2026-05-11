import { getCreatorPosts } from '@/lib/serverApi'
import type { CreatorPost } from '@/types/platform'
import CommunityManager from './CommunityManager'

export default async function CreatorCommunityPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const posts: CreatorPost[] = await getCreatorPosts(slug)

  return (
    <div className="max-w-2xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">Community</h1>
        <p className="mt-1 text-sm text-slate-400">Post announcements, prompts, and discussions.</p>
      </div>
      <CommunityManager posts={posts} spaceSlug={slug} />
    </div>
  )
}
