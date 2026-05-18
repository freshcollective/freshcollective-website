// Navigation is provided by CreatorStudioShell in /creator/layout.tsx.
// This layout only adds the content padding that the individual pages expect.
export default function SpaceCreatorLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10 md:px-10">
      {children}
    </div>
  )
}
