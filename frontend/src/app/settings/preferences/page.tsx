export default function SettingsPreferencesPage() {
  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-1 font-serif text-xl text-navy-900">Preferences</h2>
        <p className="text-sm text-slate-500">
          Personalise how the platform works for you.
        </p>
      </div>

      <div className="space-y-4">
        <PreferenceRow
          label="Email notifications"
          description="Receive updates about new events, community posts, and pathway reminders."
          comingSoon
        />
        <PreferenceRow
          label="Reminder frequency"
          description="How often you'd like gentle nudges to return to your pathway."
          comingSoon
        />
        <PreferenceRow
          label="Timezone"
          description="Used to display event times in your local time."
          comingSoon
        />
      </div>
    </div>
  )
}

function PreferenceRow({
  label,
  description,
  comingSoon,
}: {
  label: string
  description: string
  comingSoon?: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-surface px-5 py-4">
      <div className="flex-1">
        <p className="text-sm font-medium text-navy-800">{label}</p>
        <p className="mt-0.5 text-xs text-slate-400">{description}</p>
      </div>
      {comingSoon && (
        <span className="mt-0.5 shrink-0 text-[10px] font-medium text-slate-300">
          Coming soon
        </span>
      )}
    </div>
  )
}
