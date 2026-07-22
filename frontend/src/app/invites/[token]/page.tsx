import { getInviteByToken, getMe } from '@/lib/serverApi'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import InviteAcceptClient from './InviteAcceptClient'

interface Props {
  params: Promise<{ token: string }>
}

export default async function InvitePage({ params }: Props) {
  const { token } = await params

  const [invite, me] = await Promise.all([
    getInviteByToken(token),
    getMe(),
  ])

  if (!invite) notFound()

  const emailMatches = me ? me.email.toLowerCase() === invite.email.toLowerCase() : false

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-16">
      <div className="w-full max-w-md">

        {/* Header card */}
        <div
          className="mb-4 overflow-hidden rounded-2xl px-7 py-6 text-center"
          style={{ background: '#071824', border: '1px solid rgba(66,199,198,0.12)' }}
        >
          <div
            className="mx-auto mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
          />
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#55D7D2' }}>
            You&apos;re invited
          </p>
          <h1 className="mt-2 font-serif text-xl font-semibold text-white">{invite.space_name}</h1>
          {invite.name && (
            <p className="mt-1 text-[13px]" style={{ color: '#FFFFFF' }}>
              Hi {invite.name},
            </p>
          )}
        </div>

        {/* Content card */}
        <div className="rounded-2xl bg-white p-6" style={{ border: '1px solid #E2E8F0' }}>
          <p className="mb-1 text-[14px] text-black">
            You&apos;ve been invited to join{' '}
            <span className="font-semibold text-navy-900">{invite.space_name}</span>{' '}
            as a{' '}
            <span className="font-semibold capitalize">{invite.role}</span>.
          </p>
          <p className="mb-5 text-[12px] text-black">
            Invited to: {invite.email}
          </p>

          <InviteAcceptClient
            token={token}
            spaceSlug={invite.space_slug}
            spaceName={invite.space_name}
            inviteEmail={invite.email}
            isLoggedIn={!!me}
            emailMatches={emailMatches}
            currentUserEmail={me?.email ?? null}
          />

          <div className="mt-5 border-t border-slate-100 pt-4 text-center">
            <Link
              href={`/spaces/${invite.space_slug}/about`}
              className="text-[13px] text-black underline underline-offset-2 hover:text-slate-600"
            >
              View collective first
            </Link>
          </div>
        </div>

      </div>
    </div>
  )
}
