'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Avatar from '@/components/ui/Avatar'
import { apiUrl } from '@/lib/api'
import type { UserProfile } from '@/types/platform'

interface Props {
  profile: UserProfile
}

export default function ProfileForm({ profile }: Props) {
  const router = useRouter()
  const displayName = profile.display_name || profile.name || ''

  const [name, setName] = useState(profile.name ?? '')
  const [bio, setBio] = useState(profile.bio ?? '')
  const [isPublic, setIsPublic] = useState(profile.is_public)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setSaved(false)
    setError(null)

    try {
      const res = await fetch(apiUrl('/api/auth/me'), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), bio: bio.trim() || null, is_public: isPublic }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail ?? 'Something went wrong. Please try again.')
        return
      }

      setSaved(true)
      router.refresh()
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      {/* Avatar preview */}
      <div className="flex items-center gap-5">
        <Avatar name={displayName || name || 'You'} size="lg" />
        <div>
          <p className="text-sm font-medium text-navy-800">{displayName || name || 'Your name'}</p>
          <p className="text-xs text-slate-400">Avatar generated from your name</p>
        </div>
      </div>

      <div className="space-y-5">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800" htmlFor="name">
            Full name
          </label>
          <input
            id="name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name"
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800" htmlFor="bio">
            Bio
          </label>
          <textarea
            id="bio"
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            rows={3}
            maxLength={500}
            placeholder="A few words about you (optional)"
            className="w-full resize-none rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
          />
          <p className="mt-1 text-right text-xs text-slate-300">{bio.length}/500</p>
        </div>

        <div className="flex items-start gap-3 rounded-xl border border-border bg-surface px-5 py-4">
          <div className="flex-1">
            <p className="text-sm font-medium text-navy-800">Public profile</p>
            <p className="text-xs text-slate-400">
              Let other members see your name and bio in the member directory.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={isPublic}
            onClick={() => setIsPublic(!isPublic)}
            className={[
              'relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-teal-300 focus:ring-offset-1',
              isPublic ? 'bg-teal-500' : 'bg-slate-200',
            ].join(' ')}
          >
            <span
              className={[
                'absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform',
                isPublic ? 'translate-x-4' : 'translate-x-0.5',
              ].join(' ')}
            />
          </button>
        </div>
      </div>

      {error && (
        <p className="text-sm text-red-500">{error}</p>
      )}

      {saved && (
        <p className="text-sm text-teal-600">Profile saved.</p>
      )}

      <button
        type="submit"
        disabled={saving}
        className="rounded-lg bg-navy-900 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-navy-800 disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save changes'}
      </button>
    </form>
  )
}
