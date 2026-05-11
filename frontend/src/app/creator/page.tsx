import Container from '@/components/layout/Container'

export default function CreatorPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="flex-1 py-12">
        <Container>
          <div className="mb-4 h-px w-6 bg-gold-500" />
          <h1 className="mb-2 font-serif text-4xl text-navy-900">Creator Studio</h1>
          <p className="text-[#718096]">Your creator dashboard is being built.</p>
        </Container>
      </main>
    </div>
  )
}
