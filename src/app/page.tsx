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
            <p className="mb-5 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">
              <span className="inline-block h-px w-6 shrink-0 bg-gold-500" aria-hidden="true" />
              A membership for women
            </p>
            <h1 className="mb-5 font-serif text-4xl leading-tight text-navy-900 md:text-5xl lg:text-6xl">
              Move from survival into{" "}
              <em className="text-gold-500">expansion</em>
              {" "}that lasts.
            </h1>
            {/* Speaks to where she is right now, before what FC offers */}
            <p className="mb-6 font-serif text-lg italic leading-relaxed text-[#4A5568] md:text-xl">
              If you have been managing, adapting, and holding it together for a long time — you already know something needs to change.
            </p>
            <p className="mb-10 text-base leading-relaxed text-[#4A5568] md:text-lg">
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

      {/* Three pillars — each with a distinct decorative number for visual character */}
      <section className="py-20 md:py-28">
        <Container>
          <SectionHeading
            title="One structure. Three layers."
            subtitle="Everything inside Fresh Collective is designed to work together — not as separate courses, but as a connected system."
            className="mb-14 max-w-xl"
          />
          <div className="grid gap-6 md:grid-cols-3">
            {/* REAL Journey — teal */}
            <Card className="flex flex-col gap-3 bg-teal-50 border-teal-100">
              <div className="font-serif text-5xl font-light leading-none text-teal-200" aria-hidden="true">
                01
              </div>
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-teal-700">
                Start Here
              </p>
              <h3 className="font-serif text-xl text-navy-900">REAL Journey</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                The foundation every member begins with. Four phases — Recognise, Explore, Align,
                Lead — designed to be bite-sized, stabilising, and easy to return to.
              </p>
              <Link
                href="/real-journey"
                className="mt-auto text-sm font-medium text-teal-700 underline-offset-4 transition-colors hover:text-teal-900 hover:underline"
              >
                Learn more →
              </Link>
            </Card>

            {/* The Heart — gold */}
            <Card className="flex flex-col gap-3 bg-gold-50 border-gold-100">
              <div className="font-serif text-5xl font-light leading-none text-gold-100" aria-hidden="true">
                02
              </div>
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-gold-700">
                The Heart
              </p>
              <h3 className="font-serif text-xl text-navy-900">Live Layer</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Monthly live calls, community prompts, integration threads, and a space to feel
                genuinely connected. This is where Fresh Collective comes alive.
              </p>
              <Link
                href="/membership"
                className="mt-auto text-sm font-medium text-gold-700 underline-offset-4 transition-colors hover:text-gold-900 hover:underline"
              >
                Learn more →
              </Link>
            </Card>

            {/* The Rooms — navy */}
            <Card className="flex flex-col gap-3 bg-navy-50 border-navy-100">
              <div className="font-serif text-5xl font-light leading-none text-navy-100" aria-hidden="true">
                03
              </div>
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-navy-700">
                The Rooms
              </p>
              <h3 className="font-serif text-xl text-navy-900">Deepening Pathways</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Once you have your foundation, The Rooms take you deeper. Growth, Transformation,
                and Essence — each pathway building on the last.
              </p>
              <Link
                href="/membership"
                className="mt-auto text-sm font-medium text-navy-700 underline-offset-4 transition-colors hover:text-navy-900 hover:underline"
              >
                Learn more →
              </Link>
            </Card>
          </div>
        </Container>
      </section>

      {/* Community anchoring — ivory background, centred serif moment */}
      <section className="bg-ivory py-16 md:py-20">
        <Container>
          <div className="mx-auto max-w-2xl text-center">
            <div className="mx-auto mb-6 h-px w-10 bg-gold-300" />
            <p className="font-serif text-xl leading-relaxed text-navy-900 md:text-2xl">
              You are not doing this work alone. Other women are moving through the same phases,
              sitting in the same live calls, and reading the same prompts — at the same time as you.
            </p>
            <div className="mx-auto mt-6 h-px w-10 bg-gold-300" />
          </div>
        </Container>
      </section>

      {/* Two entry paths — dark navy section */}
      <section className="bg-navy-950 py-20 md:py-28">
        <Container>
          <SectionHeading
            title="Two ways in."
            subtitle="Start where you are. There is no wrong entry point."
            align="center"
            className="mb-14"
            dark
          />
          <div className="mx-auto grid max-w-3xl gap-6 md:grid-cols-2">
            {/* Path 1 — teal top border */}
            <div
              className="flex flex-col gap-5 rounded-xl bg-navy-900 p-8"
              style={{
                border: "1px solid rgba(255,255,255,0.08)",
                borderTop: "3px solid var(--color-teal-500)",
              }}
            >
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-[0.15em] text-teal-400">
                  Path 1
                </p>
                <h3 className="font-serif text-2xl text-white">REAL Journey first</h3>
              </div>
              <p className="text-sm leading-relaxed text-navy-300">
                Begin with the REAL Journey as a standalone. Work through the four phases at your
                own pace. When you are ready, step into the full membership.
              </p>
              <Link
                href="/real-journey"
                className="mt-auto inline-flex w-full items-center justify-center rounded-lg border border-teal-500 bg-teal-500 px-4 py-2.5 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-700 hover:border-teal-700"
              >
                Start with REAL Journey
              </Link>
            </div>

            {/* Path 2 — gold top border */}
            <div
              className="flex flex-col gap-5 rounded-xl bg-navy-900 p-8"
              style={{
                border: "1px solid rgba(255,255,255,0.08)",
                borderTop: "3px solid var(--color-gold-500)",
              }}
            >
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-[0.15em] text-gold-300">
                  Path 2
                </p>
                <h3 className="font-serif text-2xl text-white">Full membership</h3>
              </div>
              <p className="text-sm leading-relaxed text-navy-300">
                Join the full membership and get everything — REAL Journey, live calls, The Rooms,
                and community — from day one.
              </p>
              <Link
                href="/membership"
                className="mt-auto inline-flex w-full items-center justify-center rounded-lg border border-gold-500 bg-transparent px-4 py-2.5 text-sm font-medium text-gold-300 transition-colors duration-200 hover:bg-gold-500 hover:text-navy-950"
              >
                Explore Membership
              </Link>
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  );
}
