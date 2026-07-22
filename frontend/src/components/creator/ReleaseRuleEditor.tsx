'use client'

/**
 * ReleaseRuleEditor — creator-facing surface for the pathway drip
 * scheduling rules. Renders a small radio group and only the controls
 * relevant to the currently-selected release mode.
 *
 * Emits a `ReleaseRuleValue` upward; parents merge it into the step
 * PATCH via `releaseRulePayload(...)`. The engine that consumes these
 * values lives in `backend/app/services/pathway_release.py`.
 */

export type ReleaseType =
  | 'immediate'
  | 'days_after_enrollment'
  | 'fixed_date'
  | 'after_previous'
  | 'manual'

export interface ReleaseRuleValue {
  release_type: ReleaseType
  release_offset_days: number | null
  release_at: string | null        // ISO UTC string
  release_timezone: string | null  // e.g. 'Australia/Melbourne'
  release_previous_state: 'completed' | 'started'
}

const DEFAULT: ReleaseRuleValue = {
  release_type: 'immediate',
  release_offset_days: 7,
  release_at: null,
  release_timezone: null,
  release_previous_state: 'completed',
}

interface StepLike {
  release_type?: string | null
  release_offset_days?: number | null
  release_at?: string | null
  release_timezone?: string | null
  release_previous_state?: string | null
}

/** Build a ReleaseRuleValue from whatever a StepResponse hands us. */
export function releaseRuleFromStep(step: StepLike): ReleaseRuleValue {
  const t = (step.release_type as ReleaseType) || 'immediate'
  return {
    release_type: t,
    release_offset_days: step.release_offset_days ?? (t === 'days_after_enrollment' ? 7 : null),
    release_at: step.release_at ?? null,
    release_timezone: step.release_timezone ?? null,
    release_previous_state: (step.release_previous_state as 'completed' | 'started') || 'completed',
  }
}

/** Only include fields relevant to the chosen release type in the PATCH. */
export function releaseRulePayload(v: ReleaseRuleValue): Record<string, unknown> {
  return {
    release_type: v.release_type,
    release_offset_days: v.release_type === 'days_after_enrollment' ? (v.release_offset_days ?? 0) : null,
    release_at: v.release_type === 'fixed_date' ? v.release_at : null,
    release_timezone: v.release_type === 'fixed_date' ? v.release_timezone : null,
    release_previous_state: v.release_type === 'after_previous' ? v.release_previous_state : 'completed',
  }
}

interface Props {
  value: ReleaseRuleValue
  onChange: (next: ReleaseRuleValue) => void
}

// Member-facing labels for each release rule. Backend enum values
// (`immediate`, `days_after_enrollment`, `fixed_date`, `after_previous`,
// `manual`) are unchanged — only the visible language here.
const OPTIONS: { value: ReleaseType; label: string; hint: string }[] = [
  { value: 'immediate',             label: 'Available immediately',                 hint: 'Members can open this step as soon as they enrol.' },
  { value: 'days_after_enrollment', label: 'A set number of days after enrolment',  hint: 'The timer starts when the member enrols in the pathway.' },
  { value: 'fixed_date',            label: 'On a specific date',                    hint: 'Useful for cohort programs.' },
  { value: 'after_previous',        label: 'After the previous step is completed',  hint: 'Requires completion of the step immediately before.' },
  { value: 'manual',                label: 'Released by a caretaker',               hint: 'Useful for coaching programs.' },
]

export default function ReleaseRuleEditor({ value, onChange }: Props) {
  const displayTz = getLocalTimezone()

  function set(patch: Partial<ReleaseRuleValue>) {
    onChange({ ...value, ...patch })
  }

  const { date, time } = parseIso(value.release_at)

  return (
    <div className="space-y-3 rounded-xl border border-slate-100 bg-slate-50 p-4">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-black">Release rhythm</p>
        <p className="mt-0.5 text-[12px] text-black">
          Choose how this step becomes available to members.
        </p>
      </div>

      <div className="space-y-2">
        {OPTIONS.map((opt) => {
          const active = value.release_type === opt.value
          return (
            <label key={opt.value} className="flex cursor-pointer items-start gap-2 text-[13px] text-navy-900">
              <input
                type="radio"
                name="release-type"
                checked={active}
                onChange={() => set({ release_type: opt.value })}
                className="mt-0.5 h-4 w-4 accent-teal-500"
              />
              <span>
                <span className="font-medium">{opt.label}</span>
                <span className="ml-2 text-[12px] text-slate-500">{opt.hint}</span>
              </span>
            </label>
          )
        })}
      </div>

      {value.release_type === 'days_after_enrollment' && (
        <div className="rounded-lg bg-white p-3" style={{ border: '1px solid rgba(12,24,38,0.08)' }}>
          <label className="text-[12px] font-semibold text-black">Release after:</label>
          <div className="mt-1 flex items-center gap-2">
            <input
              type="number"
              min={0}
              max={3650}
              value={value.release_offset_days ?? 0}
              onChange={(e) => set({ release_offset_days: Math.max(0, parseInt(e.target.value, 10) || 0) })}
              className="w-20 rounded-lg border border-slate-200 px-3 py-1.5 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
            />
            <span className="text-[13px] text-navy-900">days</span>
          </div>
          <p className="mt-1 text-[11.5px] italic text-slate-500">
            Day 0 releases the moment they enrol; Day 7 releases a week later.
          </p>
        </div>
      )}

      {value.release_type === 'fixed_date' && (
        <div className="rounded-lg bg-white p-3" style={{ border: '1px solid rgba(12,24,38,0.08)' }}>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-black">Release date</label>
              <input
                type="date"
                value={date}
                onChange={(e) => {
                  const iso = combineIso(e.target.value, time)
                  set({ release_at: iso, release_timezone: value.release_timezone ?? displayTz })
                }}
                className="mt-1 rounded-lg border border-slate-200 px-3 py-1.5 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-black">Release time</label>
              <input
                type="time"
                value={time}
                onChange={(e) => {
                  const iso = combineIso(date, e.target.value)
                  set({ release_at: iso, release_timezone: value.release_timezone ?? displayTz })
                }}
                className="mt-1 rounded-lg border border-slate-200 px-3 py-1.5 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
              />
            </div>
            <span
              className="mb-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.62)' }}
            >
              {value.release_timezone || displayTz}
            </span>
          </div>
          {value.release_at && (
            <p className="mt-2 text-[12.5px] italic" style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}>
              Releases {new Date(value.release_at).toLocaleString('en-AU', {
                weekday: 'long', day: 'numeric', month: 'long',
                hour: 'numeric', minute: '2-digit', hour12: true,
              })} {value.release_timezone || displayTz}
            </p>
          )}
        </div>
      )}

      {value.release_type === 'after_previous' && (
        <div className="rounded-lg bg-white p-3" style={{ border: '1px solid rgba(12,24,38,0.08)' }}>
          <p className="text-[12.5px] text-navy-900">
            This step unlocks immediately once the previous step is <span className="font-medium">completed</span>.
          </p>
          <p className="mt-1 text-[11.5px] italic text-slate-500">
            The first step in the pathway is always available regardless of this rule.
          </p>
        </div>
      )}

      {value.release_type === 'manual' && (
        <div className="rounded-lg bg-white p-3" style={{ border: '1px solid rgba(12,24,38,0.08)' }}>
          <p className="text-[12.5px] text-navy-900">
            This step remains locked until a caretaker releases it for the member.
          </p>
        </div>
      )}
    </div>
  )
}

function getLocalTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Local time'
  } catch {
    return 'Local time'
  }
}

function parseIso(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: '', time: '' }
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return { date: '', time: '' }
  const pad = (n: number) => n.toString().padStart(2, '0')
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  }
}

function combineIso(date: string, time: string): string | null {
  if (!date || !time) return null
  const local = new Date(`${date}T${time}`)
  if (Number.isNaN(local.getTime())) return null
  return local.toISOString()
}
