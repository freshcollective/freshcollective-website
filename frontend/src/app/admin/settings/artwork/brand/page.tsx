import Link from 'next/link'

import { getAdminBrandAssets } from '@/lib/serverApi'
import BrandAssetsClient from './BrandAssetsClient'

/**
 * World Management → Artwork → Fresh Collective Brand.
 *
 * A section of the existing Artwork area rather than a second asset
 * manager: the same storage, the same public URL prefix, the same
 * table. What differs is that these are *roles* the brand fills rather
 * than slots a photograph sits in — so each one carries approved
 * artwork bundled in the repo, and can honestly report having none.
 */
export const metadata = {
  title: 'Fresh Collective Brand — World Management',
}

export default async function BrandAssetsPage() {
  const groups = await getAdminBrandAssets()
  return (
    <div className="mx-auto max-w-[900px] px-6 py-10 md:px-10">
      <Link
        href="/admin/settings/artwork"
        className="text-[13px] transition-opacity hover:opacity-60"
        style={{ color: 'rgba(12, 24, 38, 0.55)' }}
      >
        ← World Artwork
      </Link>
      <BrandAssetsClient initialGroups={groups} />
    </div>
  )
}
