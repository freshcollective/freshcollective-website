import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";
import Card from "@/components/ui/Card";
import SectionHeading from "@/components/ui/SectionHeading";

export default function Home() {
  return (
    <SiteShell>
      {/* Hero */}
      <section className="border-b border-border py-24 md:py-32">
        <Container>
          <div className="max-w-2xl">
            <p className="mb-5 text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">
              A membership for women
            </p>
            <h1 className="mb-6 font-serif text-4xl leading-tight text-navy-900 md:text-5xl lg:text-6xl">
              Move from survival into expansion that lasts.
            </h1>
            <p className="mb-10 text-lg leading-relaxed text-[#4A5568]">
              Fresh Collective is a structured transformation membership — one foundation, a live
              community layer, and deepening pathways — for women who are ready to stop coping and
              start leading their own lives.
            </p>
            <div className="flex flex-wrap gap-4">
              <Link
                href="/real-journey"
                className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-6 py-3 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700"
              >
                Start with REAL Journey
              </Link>
              <Link
                href="/membership"
                className="inline-flex items-center justify-center rounded-lg border border-navy-300 bg-transparent px-6 py-3 text-base font-medium text-navy-900 transition-colors duration-200 hover:border-navy-500 hover:bg-navy-50"
              >
                Explore Membership
              </Link>
            </div>
          </div>
        </Container>
      </section>

      {/* Three pillars */}
      <section className="py-20 md:py-28">
        <Container>
          <SectionHeading
            title="One structure. Three layers."
            subtitle="Everything inside Fresh Collective is designed to work together — not as separate courses, but as a connected system."
            className="mb-14 max-w-xl"
          />
          <div className="grid gap-6 md:grid-cols-3">
            <Card className="flex flex-col gap-4">
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-teal-600">
                Start Here
              </p>
              <h3 className="font-serif text-xl text-navy-900">REAL Journey</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                The foundation every member begins with. Four phases — Recognise, Explore, Align,
                Lead — designed to be bite-sized, stabilising, and easy to return to.
              </p>
              <Link
                href="/real-journey"
                className="mt-auto text-sm font-medium text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
              >
                Learn more →
              </Link>
            </Card>

            <Card className="flex flex-col gap-4">
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-teal-600">
                The Heart
              </p>
              <h3 className="font-serif text-xl text-navy-900">Live Layer</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Monthly live calls, community prompts, integration threads, and a space to feel
                genuinely connected. This is where Fresh Collective comes alive.
              </p>
              <Link
                href="/membership"
                className="mt-auto text-sm font-medium text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
              >
                Learn more →
              </Link>
            </Card>

            <Card className="flex flex-col gap-4">
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-teal-600">
                The Rooms
              </p>
              <h3 className="font-serif text-xl text-navy-900">Deepening Pathways</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Once you have your foundation, The Rooms take you deeper. Growth, Transformation,
                and Essence — each pathway building on the last.
              </p>
              <Link
                href="/membership"
                className="mt-auto text-sm font-medium text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
              >
                Learn more →
              </Link>
            </Card>
          </div>
        </Container>
      </section>

      {/* Two entry paths */}
      <section className="border-t border-border bg-navy-50 py-20 md:py-28">
        <Container>
          <SectionHeading
            title="Two ways in."
            subtitle="Start where you are. There is no wrong entry point."
            align="center"
            className="mb-14"
          />
          <div className="mx-auto grid max-w-3xl gap-6 md:grid-cols-2">
            <Card className="flex flex-col gap-5 p-8">
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-[0.15em] text-gold-700">
                  Path 1
                </p>
                <h3 className="font-serif text-2xl text-navy-900">REAL Journey first</h3>
              </div>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Begin with the REAL Journey as a standalone. Work through the four phases at your
                own pace. When you are ready, step into the full membership.
              </p>
              <Link
                href="/real-journey"
                className="mt-auto inline-flex w-full items-center justify-center rounded-lg border border-transparent bg-teal-500 px-4 py-2.5 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-700"
              >
                Start with REAL Journey
              </Link>
            </Card>

            <Card className="flex flex-col gap-5 p-8">
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-[0.15em] text-gold-700">
                  Path 2
                </p>
                <h3 className="font-serif text-2xl text-navy-900">Full membership</h3>
              </div>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Join the full membership and get everything — REAL Journey, live calls, The Rooms,
                and community — from day one.
              </p>
              <Link
                href="/membership"
                className="mt-auto inline-flex w-full items-center justify-center rounded-lg border border-transparent bg-teal-500 px-4 py-2.5 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-700"
              >
                Explore Membership
              </Link>
            </Card>
          </div>
        </Container>
      </section>
    </SiteShell>
  );
}
