'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import Avatar from '@/components/ui/Avatar'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type { UserProfile } from '@/types/platform'

interface Props {
  profile: UserProfile
}

export default function ProfileForm({ profile }: Props) {
  const router = useRouter()
  const displayName = profile.display_name || profile.name || ''

  const [name, setName]       = useState(profile.name ?? '')
  const [tagline, setTagline] = useState(profile.profile_tagline ?? '')
  const [bio, setBio]         = useState(profile.bio ?? '')
  const [isPublic, setIsPublic] = useState(profile.is_public)
  const [saving, setSaving]   = useState(false)
  const [saved, setSaved]     = useState(false)
  const [error, setError]     = useState<string | null>(null)

  // Store the resolved full URL so Avatar renders correctly immediately after upload
  const [avatarUrl, setAvatarUrl] = useState<string | null>(
    resolveMediaUrl(profile.avatar_url)
  )
  const [uploading, setUploading]     = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleAvatarChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(apiUrl('/api/auth/me/avatar'), {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Upload failed (${res.status})`)
      }
      const updated = await res.json()
      // Resolve the returned relative path to a full URL immediately
      setAvatarUrl(resolveMediaUrl(updated.avatar_url) ?? null)
      router.refresh()
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

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
        body: JSON.stringify({
          name: name.trim(),
          bio: bio.trim() || null,
          profile_tagline: tagline.trim() || null,
          is_public: isPublic,
        }),
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

  const previewName = name.trim() || displayName || 'You'

  return (
    <form onSubmit={handleSubmit} className="space-y-8">

      {/* ── Avatar area ── */}
      <div
        className="flex items-center gap-6 rounded-2xl border border-border bg-white p-6"
        style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
      >
        <div className="relative shrink-0">
          <Avatar name={previewName} avatarUrl={avatarUrl} size="xl" />
          {/* Pencil button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="absolute -bottom-1 -right-1 flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-navy-900 text-white shadow transition-colors hover:bg-navy-700 disabled:opacity-50"
            title={avatarUrl ? 'Change photo' : 'Upload photo'}
            aria-label={avatarUrl ? 'Change photo' : 'Upload photo'}
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
              <path d="M14.846 2.508a2.5 2.5 0 0 0-3.536 0L2.5 11.318V13.5h2.182l8.81-8.81a2.5 2.5 0 0 0 0-3.182zM4.096 12.5H3.5v-.596l7.5-7.5.596.596-7.5 7.5z"/>
            </svg>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={handleAvatarChange}
          />
        </div>

        <div>
          <p className="text-[15px] font-semibold text-navy-900">{previewName}</p>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="mt-1 text-[13px] text-teal-600 transition-colors hover:text-teal-700 disabled:opacity-50"
          >
            {uploading ? 'Uploading…' : avatarUrl ? 'Change photo' : 'Upload photo'}
          </button>
          <p className="mt-0.5 text-[12px] text-slate-400">
            {avatarUrl ? 'JPG, PNG or WebP.' : 'Upload a photo, or keep your initials — both look great.'}
          </p>
        </div>
      </div>

      {uploadError && (
        <p
          className="rounded-xl px-4 py-2.5 text-[13px]"
          style={{ background: 'rgba(239,68,68,0.06)', color: '#dc2626', border: '1px solid rgba(239,68,68,0.18)' }}
        >
          {uploadError}
        </p>
      )}

      {/* ── Fields ── */}
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
            className="w-full rounded-xl border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
          />
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800" htmlFor="tagline">
            Profile tagline
          </label>
          <input
            id="tagline"
            type="text"
            value={tagline}
            onChange={(e) => setTagline(e.target.value)}
            maxLength={150}
            placeholder="e.g. Pattern spotter, quiet powerhouse, joy seeker"
            className="w-full rounded-xl border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
          />
          <p className="mt-1 text-xs text-slate-400">A short line that gives people a feel for you.</p>
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800" htmlFor="bio">
            Bio
          </label>
          <textarea
            id="bio"
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            rows={4}
            maxLength={500}
            placeholder="A few words about you (optional)"
            className="w-full resize-none rounded-xl border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
          />
          <p className="mt-1 text-right text-xs text-slate-300">{bio.length}/500</p>
        </div>

        <div className="flex items-start gap-3 rounded-xl border border-border bg-white px-5 py-4">
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

      {error && <p className="text-sm text-red-500">{error}</p>}
      {saved && <p className="text-sm text-teal-600">Profile saved.</p>}

      <button
        type="submit"
        disabled={saving}
        className="rounded-xl px-7 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
      >
        {saving ? 'Saving…' : 'Save changes'}
      </button>
    </form>
  )
}
