import Container from '@/components/layout/Container'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceEventsPage({ params }: Props) {
  const { slug } = await params

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="flex-1 py-12">
        <Container>
          <div className="mb-4 h-px w-6 bg-gold-500" />
          <h1 className="mb-2 font-serif text-4xl text-navy-900">Events</h1>
          <p className="mb-1 text-sm text-[#718096]">Space: {slug}</p>
          <p className="text-[#718096]">Events for this space are being built.</p>
        </Container>
      </main>
    </div>
  )
}
