'use client'

/**
 * Leave Collective — the member-facing end of a membership.
 *
 * Lives on the Membership card for Collectives where the person is a
 * **Member**. Creator- and moderator-held cards never render it: ending
 * a caretaker relationship is a different operation with different
 * consequences for the Collective, and the server refuses it here too.
 *
 * Discoverable, not dominant (§14): a quiet text button at the end of
 * the card's own row, not a danger button competing with the Collective
 * it belongs to. The destructive weight belongs in the dialog, where the
 * consequences are, which is where the ``danger`` variant appears.
 *
 * Consequences are **fetched, not assumed.** The dialog opens on a
 * ``GET …/my-membership/departure`` so it can say what this member
 * actually has at stake — passes, bookings, Offerings kept — instead of
 * reciting a generic warning. The same endpoint reports whether leaving
 * is possible at all, and it evaluates the same refusals the DELETE
 * does, so the confirm button is never offered for a departure the
 * server would reject.
 *
 * @see docs/fresh-design-language.md §14
 */

import { useCallback, useState } from 'react'
import { Button, Modal, useToast } from '@/components/platform'
import { apiUrl } from '@/lib/api'
import {
  departureBlockedMessage,
  departureConsequenceLines,
  type DeparturePreview,
} from '@/lib/leaveCollective'

interface Props {
  spaceSlug: string
  spaceName: string
  /** Called after a successful departure so the list can drop the card
   *  without a round trip to the server. */
  onLeft: (spaceSlug: string) => void
}

export default function LeaveCollective({
  spaceSlug, spaceName, onLeft,
}: Props) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState<DeparturePreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const openDialog = useCallback(async () => {
    setOpen(true)
    setPreview(null)
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(
        apiUrl(`/api/spaces/${spaceSlug}/my-membership/departure`),
        { credentials: 'include' },
      )
      if (!res.ok) {
        setError('We could not check what leaving would mean. Please try again.')
        return
      }
      setPreview((await res.json()) as DeparturePreview)
    } catch {
      setError('We could not check what leaving would mean. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [spaceSlug])

  const close = useCallback(() => {
    if (leaving) return
    setOpen(false)
  }, [leaving])

  async function confirmLeave() {
    setLeaving(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/spaces/${spaceSlug}/my-membership`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) {
        // A failed removal must never read as a successful departure.
        // The card stays, the dialog stays open, and the server's own
        // reason is shown when it sent one — the refusals here are
        // specific and worth reading ("you have a payment plan in
        // progress"), unlike a generic retry prompt.
        let detail: string | null = null
        try {
          const body = await res.json()
          if (typeof body?.detail === 'string') detail = body.detail
        } catch {
          // No JSON body — fall through to the generic message.
        }
        setError(detail ?? 'We could not complete this. Please try again.')
        return
      }
      setOpen(false)
      toast.show(
        preview && preview.offerings_retained > 0
          ? `You have left ${spaceName}. Anything you acquired is still in `
            + 'Your Collection.'
          : `You have left ${spaceName}.`,
        { tone: 'success' },
      )
      onLeft(spaceSlug)
    } catch {
      setError('We could not complete this. Please try again.')
    } finally {
      setLeaving(false)
    }
  }

  const blocked = preview ? departureBlockedMessage(preview) : null
  const canConfirm = Boolean(preview?.can_leave) && !loading

  return (
    <>
      <button
        type="button"
        onClick={openDialog}
        className="text-[12px] font-medium text-black underline decoration-border underline-offset-2 transition-colors hover:text-teal-700"
      >
        Leave Collective
      </button>

      <Modal
        open={open}
        onClose={close}
        title={`Leave ${spaceName}?`}
        size="sm"
        actions={
          <>
            <Button
              variant="tertiary"
              size="md"
              onClick={close}
              disabled={leaving}
            >
              Cancel
            </Button>
            {canConfirm && (
              <Button
                variant="danger"
                size="md"
                onClick={confirmLeave}
                loading={leaving}
              >
                Leave Collective
              </Button>
            )}
          </>
        }
      >
        {loading && (
          <p className="text-[13px] text-black">Checking your membership…</p>
        )}

        {!loading && blocked && (
          <p className="text-[13px] leading-relaxed text-navy-800">{blocked}</p>
        )}

        {!loading && preview?.can_leave && (
          <div className="flex flex-col gap-2.5">
            {departureConsequenceLines(preview).map((line) => (
              <p
                key={line}
                className="text-[13px] leading-relaxed text-navy-800"
              >
                {line}
              </p>
            ))}
          </div>
        )}

        {error && (
          <p role="alert" className="mt-3 text-[13px] leading-relaxed text-red-700">
            {error}
          </p>
        )}
      </Modal>
    </>
  )
}
