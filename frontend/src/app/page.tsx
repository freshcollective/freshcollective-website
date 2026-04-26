import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";
import Card from "@/components/ui/Card";
import SectionHeading from "@/components/ui/SectionHeading";

export default function Home() {
  return (
    <SiteShell>
      {/* Hero — split layout: text left, platform preview right */}
      <section className="border-b border-border bg-ivory py-24 md:py-32 overflow-hidden">
        <Container>
          <div className="grid gap-12 md:grid-cols-[55%_45%] md:gap-10 md:items-center">

            {/* Left: message */}
            <div>
              <p className="mb-5 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">
                <span className="inline-block h-px w-6 shrink-0 bg-gold-500" aria-hidden="true" />
                A membership for women
              </p>
              <h1 className="mb-5 font-serif text-5xl leading-tight text-navy-900 md:text-6xl lg:text-7xl">
                Move from survival into{" "}
                <em className="text-gold-500">expansion</em>
                {" "}that lasts.
              </h1>
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
                  className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-7 py-3.5 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700"
                >
                  Start with REAL Journey
                </Link>
                <Link
                  href="/membership"
                  className="inline-flex items-center justify-center rounded-lg border border-navy-300 bg-transparent px-7 py-3.5 text-base font-medium text-navy-900 transition-colors duration-200 hover:border-navy-500 hover:bg-navy-50"
                >
                  Explore Membership
                </Link>
              </div>
            </div>

            {/* Right: platform preview panel */}
            <div className="hidden md:block">
              {/* IMAGE_PLACEHOLDER: Warm editorial photo — woman journalling or in quiet reflection. Grounded, calm, premium. Replace this entire div with a Next.js Image component when photography is available. */}
              <div className="relative">

                {/* Main dark panel */}
                <div
                  className="rounded-2xl bg-navy-950 p-5"
                  style={{ boxShadow: "0 32px 80px rgba(15,27,48,0.28)" }}
                >
                  {/* Panel header */}
                  <div className="mb-4 flex items-center gap-2.5">
                    <div className="h-2 w-2 rounded-full bg-teal-500" />
                    <span className="text-xs font-medium text-navy-500">Fresh Collective</span>
                  </div>

                  {/* REAL Journey progress card */}
                  <div
                    className="mb-3 rounded-xl bg-navy-900 p-4"
                    style={{ border: "1px solid rgba(255,255,255,0.07)" }}
                  >
                    <div className="mb-3 flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-widest text-teal-400">
                        REAL Journey
                      </span>
                      <span className="rounded-full bg-teal-900 px-2 py-0.5 text-[10px] font-medium text-teal-300">
                        Phase 1 of 4
                      </span>
                    </div>
                    <p className="mb-1.5 text-sm font-medium text-white">Recognise</p>
                    <p className="text-xs leading-relaxed text-navy-300">
                      Seeing clearly what is true right now.
                    </p>
                    <div className="mt-3 flex gap-1">
                      <div className="h-1 flex-1 rounded-full bg-teal-500" />
                      <div className="h-1 flex-1 rounded-full bg-navy-700" />
                      <div className="h-1 flex-1 rounded-full bg-navy-700" />
                      <div className="h-1 flex-1 rounded-full bg-navy-700" />
                    </div>
                  </div>

                  {/* Live call card */}
                  <div
                    className="rounded-xl bg-navy-900 p-4"
                    style={{ border: "1px solid rgba(255,255,255,0.07)" }}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="text-xs font-semibold uppercase tracking-widest text-gold-400">
                          Live Call
                        </span>
                        <p className="mt-1 text-sm font-medium text-white">Monthly gathering</p>
                        <p className="mt-0.5 text-xs text-navy-300">60 min · Structured · Led</p>
                      </div>
                      <div
                        className="ml-4 flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
                        style={{ background: "rgba(184,144,42,0.15)" }}
                      >
                        <div className="h-2.5 w-2.5 rounded-full bg-gold-400" />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Offset community card below */}
                <div className="ml-6 mt-3 rounded-xl border border-teal-100 bg-teal-50 p-4">
                  <p className="mb-1 text-xs font-semibold text-teal-700">Community</p>
                  <p className="text-xs leading-relaxed text-[#4A5568]">
                    Women moving through the same phases, at the same time as you.
                  </p>
                </div>
              </div>
            </div>

          </div>
        </Container>
      </section>

      {/* Platform layers — asymmetric: REAL featured, then 2-col */}
      <section className="py-20 md:py-28">
        <Container>
          <SectionHeading
            title="One structure. Three layers."
            subtitle="Everything inside Fresh Collective is designed to work together — not as separate courses, but as a connected system."
            className="mb-14 max-w-xl"
          />

          <div className="space-y-6">
            {/* REAL Journey — full-width featured card */}
            <div
              className="overflow-hidden rounded-xl border border-teal-100 bg-teal-50"
              style={{ boxShadow: "var(--fc-shadow-sm)" }}
            >
              <div className="flex flex-col md:flex-row md:items-stretch">
                <div className="flex-1 p-8 md:p-10">
                  <div
                    className="font-serif text-[7rem] font-light leading-none text-teal-200 select-none -mb-3"
                    aria-hidden="true"
                  >
                    01
                  </div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-teal-700">
                    Start Here
                  </p>
                  <h3 className="mb-3 font-serif text-2xl text-navy-900">REAL Journey</h3>
                  <p className="mb-5 max-w-md text-sm leading-relaxed text-[#4A5568]">
                    The foundation every member begins with. Four phases — Recognise, Explore, Align,
                    Lead — designed to be bite-sized, stabilising, and easy to return to.
                  </p>
                  <Link
                    href="/real-journey"
                    className="text-sm font-medium text-teal-700 underline-offset-4 transition-colors hover:text-teal-900 hover:underline"
                  >
                    Learn more →
                  </Link>
                </div>

                {/* IMAGE_PLACEHOLDER: Editorial photo — woman writing in a journal, warm natural light, grounded and focused. Portrait orientation, right-aligned crop. */}
                <div className="flex min-h-[180px] items-center justify-center bg-teal-100/60 md:w-64 md:shrink-0">
                  <div className="text-center px-6">
                    <div className="font-serif text-4xl font-light tracking-[0.5em] text-teal-400">
                      REAL
                    </div>
                    <div className="mx-auto mt-3 h-px w-full bg-teal-200" />
                    <div className="mt-3 flex justify-center gap-2">
                      {["R", "E", "A", "L"].map((letter) => (
                        <div
                          key={letter}
                          className="flex h-9 w-9 items-center justify-center rounded-full bg-white/70 font-serif text-sm font-medium text-teal-700"
                        >
                          {letter}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Live Layer + Deepening Pathways — 2-col */}
            <div className="grid gap-6 md:grid-cols-2">
              <Card className="flex flex-col gap-3 bg-gold-50 border-gold-100">
                <div
                  className="font-serif text-8xl font-light leading-none text-gold-200 select-none"
                  aria-hidden="true"
                >
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

              <Card className="flex flex-col gap-3 bg-navy-50 border-navy-100">
                <div
                  className="font-serif text-8xl font-light leading-none text-navy-200 select-none"
                  aria-hidden="true"
                >
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
          </div>
        </Container>
      </section>

      {/* Stats band — structural rhythm break */}
      <section className="bg-navy-950 py-12 md:py-14">
        <Container>
          <div className="grid grid-cols-3">
            <div className="px-6 py-4 text-center md:py-6">
              <div className="font-serif text-4xl font-light text-white md:text-5xl">4</div>
              <div className="mt-2 text-xs font-medium uppercase tracking-widest text-navy-300">
                Phases
              </div>
            </div>
            <div
              className="px-6 py-4 text-center md:py-6"
              style={{ borderLeft: "1px solid rgba(255,255,255,0.1)", borderRight: "1px solid rgba(255,255,255,0.1)" }}
            >
              <div className="font-serif text-4xl font-light text-gold-400 md:text-5xl">1</div>
              <div className="mt-2 text-xs font-medium uppercase tracking-widest text-navy-300">
                Live call monthly
              </div>
            </div>
            <div className="px-6 py-4 text-center md:py-6">
              <div className="font-serif text-4xl font-light text-teal-400 md:text-5xl">∞</div>
              <div className="mt-2 text-xs font-medium uppercase tracking-widest text-navy-300">
                Your pace
              </div>
            </div>
          </div>
        </Container>
      </section>

      {/* Community anchoring — editorial serif moment */}
      <section className="bg-ivory py-20 md:py-28">
        <Container>
          <div className="mx-auto max-w-3xl text-center">
            <div className="mx-auto mb-8 h-px w-10 bg-gold-300" />
            <p className="font-serif text-2xl leading-relaxed text-navy-900 md:text-3xl md:leading-relaxed">
              You are not doing this work alone. Other women are moving through the same phases,
              sitting in the same live calls, and reading the same prompts — at the same time as you.
            </p>
            <div className="mx-auto mt-8 h-px w-10 bg-gold-300" />
          </div>
        </Container>
      </section>

      {/* Two entry paths — dark navy */}
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
            <div
              className="flex flex-col gap-5 rounded-xl bg-navy-900 p-8"
              style={{
                border: "1px solid rgba(255,255,255,0.08)",
                borderTop: "4px solid var(--color-teal-500)",
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
                className="mt-auto inline-flex w-full items-center justify-center rounded-lg border border-teal-500 bg-teal-500 px-4 py-3 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-700 hover:border-teal-700"
              >
                Start with REAL Journey
              </Link>
            </div>

            <div
              className="flex flex-col gap-5 rounded-xl bg-navy-900 p-8"
              style={{
                border: "1px solid rgba(255,255,255,0.08)",
                borderTop: "4px solid var(--color-gold-500)",
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
                className="mt-auto inline-flex w-full items-center justify-center rounded-lg border border-gold-500 bg-transparent px-4 py-3 text-sm font-medium text-gold-300 transition-colors duration-200 hover:bg-gold-500 hover:text-navy-950"
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
