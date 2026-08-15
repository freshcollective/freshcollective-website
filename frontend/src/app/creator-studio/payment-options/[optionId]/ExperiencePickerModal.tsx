'use client'

import { useEffect, useMemo, useState } from 'react'
import { Button, Modal, SearchInput } from '@/components/platform'

/**
 * Experience picker for the central Payment Option editor.
 *
 * Replaces the native ``<select>`` in ``AddGrantPicker`` — that
 * approach breaks down as soon as a Collective has more than a
 * dozen experiences (EMBODY already has ~50 Series children).
 *
 * Behaviour:
 *   * Filterable text search across title + subtitle.
 *   * Three grouped lists — Pathways / Gathering Series /
 *     Gatherings — each in a constrained scrollable area.
 *   * "Already added" experiences are shown but non-selectable,
 *     with an inline pill, so the Creator can see they can't be
 *     double-granted (also enforced server-side via the grant
 *     target validators).
 *   * For a Gathering Series pick, prompts an allowance step
 *     (``Sessions each week`` / ``Total sessions``) before commit,
 *     mirroring the Series-only extras the API accepts.
 *   * Standalone Gathering picks show the "Coming later" warning —
 *     PaymentOption-based Gathering checkout is not yet wired.
 *
 * Series-child Gatherings are excluded upstream by the
 * ``/commerce/grantable-experiences`` endpoint, so this component
 * never has to worry about filtering them out.
 */

export interface Experience {
  id: string
  title: string
  slug: string | null
  kind: 'pathway' | 'event_series' | 'gathering'
  status: string
  subtitle: string | null
}

interface Props {
  open: boolean
  onClose: () => void
  experiences: Experience[]
  alreadyGrantedIds: Set<string>
  onAdd: (
    exp: Experience,
    extras?: { sessions_per_week?: number; total_sessions?: number },
  ) => Promise<void>
}

type Step = 'pick' | 'series-allowance'

const KIND_LABEL: Record<Experience['kind'], string> = {
  pathway: 'Pathways',
  event_series: 'Gathering Series',
  gathering: 'Gatherings',
}

const KIND_ORDER: Experience['kind'][] = ['pathway', 'event_series', 'gathering']

export default function ExperiencePickerModal({
  open, onClose, experiences, alreadyGrantedIds, onAdd,
}: Props) {
  const [q, setQ] = useState('')
  const [step, setStep] = useState<Step>('pick')
  const [chosen, setChosen] = useState<Experience | null>(null)
  const [spw, setSpw] = useState('')
  const [tot, setTot] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Reset on open/close.
  useEffect(() => {
    if (open) {
      setQ('')
      setStep('pick')
      setChosen(null)
      setSpw('')
      setTot('')
      setSubmitting(false)
    }
  }, [open])

  const grouped = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const match = (e: Experience) =>
      !needle
      || e.title.toLowerCase().includes(needle)
      || (e.subtitle?.toLowerCase().includes(needle) ?? false)
    const g: Record<Experience['kind'], Experience[]> = {
      pathway: [], event_series: [], gathering: [],
    }
    for (const e of experiences) {
      if (match(e)) g[e.kind].push(e)
    }
    return g
  }, [experiences, q])

  function pickExperience(e: Experience) {
    setChosen(e)
    if (e.kind === 'event_series') {
      setStep('series-allowance')
    } else {
      void commit(e)
    }
  }

  async function commit(
    e: Experience,
    extras?: { sessions_per_week?: number; total_sessions?: number },
  ) {
    setSubmitting(true)
    try {
      await onAdd(e, extras)
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  const totalMatches =
    grouped.pathway.length + grouped.event_series.length + grouped.gathering.length

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={
        step === 'series-allowance' && chosen
          ? `Include "${chosen.title}"`
          : 'Add an experience'
      }
      actions={
        step === 'series-allowance' ? (
          <>
            <Button variant="tertiary" size="md" onClick={() => setStep('pick')} disabled={submitting}>
              Back
            </Button>
            <Button
              variant="primary"
              size="md"
              disabled={submitting || !chosen}
              onClick={() => {
                if (!chosen) return
                void commit(chosen, {
                  sessions_per_week: spw === '' ? undefined : Number(spw),
                  total_sessions: tot === '' ? undefined : Number(tot),
                })
              }}
              loading={submitting}
            >
              Add to Payment Option
            </Button>
          </>
        ) : (
          <Button variant="tertiary" size="md" onClick={onClose}>Close</Button>
        )
      }
    >
      {step === 'pick' && (
        <div className="space-y-4">
          <SearchInput
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onClear={() => setQ('')}
            placeholder="Search Pathways, Series or Gatherings…"
          />

          <div className="max-h-[60vh] space-y-5 overflow-y-auto pr-1">
            {KIND_ORDER.map((kind) => {
              const items = grouped[kind]
              if (items.length === 0) return null
              // Standalone Gathering grants are structurally
              // unsupported by finite Payment Option checkout today
              // (checkout_orchestration refuses them via
              // ``check_option_fulfillable_or_raise``). Keep the
              // section visible for roadmap clarity but disable
              // Add so a Creator can't author a grant fulfilment
              // would immediately reject. Historical Gathering
              // grants on existing Payment Options are untouched.
              const kindUnsupported = kind === 'gathering'
              return (
                <section key={kind}>
                  <div className="mb-2 flex items-center gap-2">
                    <h3 className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
                      {KIND_LABEL[kind]}
                    </h3>
                    {kindUnsupported && (
                      <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-600 ring-1 ring-slate-200">
                        Not yet available for Payment Options
                      </span>
                    )}
                  </div>
                  {kindUnsupported && (
                    <p className="mb-2 text-[11.5px] leading-relaxed text-slate-500">
                      Standalone Gatherings can&rsquo;t be bundled into a Payment
                      Option yet — use a Gathering Series if you need to grant
                      Gathering access. This section will re-open once payment-option
                      Gathering fulfilment is enabled.
                    </p>
                  )}
                  <ul className="space-y-1">
                    {items.map((e) => {
                      const already = alreadyGrantedIds.has(e.id)
                      const disabled = already || submitting || kindUnsupported
                      return (
                        <li key={e.id}>
                          <button
                            type="button"
                            disabled={disabled}
                            onClick={() => {
                              if (kindUnsupported) return
                              pickExperience(e)
                            }}
                            aria-disabled={disabled}
                            title={
                              kindUnsupported
                                ? 'Not yet available for Payment Options'
                                : undefined
                            }
                            className={`flex w-full items-center justify-between gap-3 rounded-md border px-3 py-2 text-left transition-colors ${
                              disabled
                                ? 'cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400'
                                : 'border-slate-200 bg-white hover:border-teal-300 hover:bg-teal-50/40'
                            }`}
                          >
                            <div className="min-w-0">
                              <div className="truncate text-[13.5px] font-medium text-navy-900">
                                {e.title}
                              </div>
                              {e.subtitle && (
                                <div className="mt-0.5 text-[11.5px] text-slate-500">
                                  {e.subtitle}
                                </div>
                              )}
                            </div>
                            {already ? (
                              <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
                                Already added
                              </span>
                            ) : kindUnsupported ? (
                              <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
                                Not available
                              </span>
                            ) : (
                              <span className="shrink-0 rounded-full bg-teal-50 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-teal-700">
                                Add
                              </span>
                            )}
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </section>
              )
            })}

            {totalMatches === 0 && (
              <p className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-[13px] italic text-slate-500">
                No experiences match “{q}”.
              </p>
            )}
            {experiences.length === 0 && (
              <p className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-[13px] italic text-slate-500">
                No experiences to add yet. Create Pathways or Gathering
                Series first from their Creator Studio sections.
              </p>
            )}
          </div>
        </div>
      )}

      {step === 'series-allowance' && chosen && (
        <div className="space-y-4">
          <p className="rounded-md bg-slate-50 px-3 py-2.5 text-[13px] text-slate-700">
            Set how many Gatherings from <strong>{chosen.title}</strong> a
            member can book with this Payment Option. Leave both blank to
            grant unlimited access for the Series's period.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Sessions each week</span>
              <input
                type="number" min={0} value={spw}
                onChange={(e) => setSpw(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
              />
            </label>
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Total sessions</span>
              <input
                type="number" min={0} value={tot}
                onChange={(e) => setTot(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
              />
            </label>
          </div>
        </div>
      )}
    </Modal>
  )
}
