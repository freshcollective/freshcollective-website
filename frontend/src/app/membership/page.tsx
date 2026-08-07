import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";
import Card from "@/components/ui/Card";
import SectionHeading from "@/components/ui/SectionHeading";

export default function MembershipPage() {
  return (
    <SiteShell>
      {/* Hero — split layout */}
      <section className="border-b border-border py-20 md:py-28">
        <Container>
          <div className="grid gap-12 md:grid-cols-[55%_45%] md:gap-10 md:items-center">
            <div>
              <p className="mb-5 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">
                <span className="inline-block h-px w-6 shrink-0 bg-gold-500" aria-hidden="true" />
                Full membership
              </p>
              <h1 className="mb-6 font-serif text-5xl leading-tight text-navy-900 md:text-6xl">
                Everything you need to move from survival into{" "}
                <em className="text-gold-500">expansion.</em>
              </h1>
              <p className="mb-10 text-lg leading-relaxed text-[#4A5568]">
                This is not a content library. There is nothing to binge or fall behind on. Fresh
                Collective gives you a structured foundation, a live community layer, deepening
                pathways, and the people who make the work real.
              </p>
              {/* STRIPE_INTEGRATION */}
              <button className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-7 py-3.5 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700">
                Join Fresh Collective
              </button>
            </div>

            {/* Right: membership layers preview */}
            {/* IMAGE_PLACEHOLDER: Warm group or connection image — women in conversation, or a single woman feeling settled and present. Editorial tone. Replace this div with Next.js Image when photography is available. */}
            <div className="hidden md:block">
              <div className="space-y-3">
                {[
                  { label: "Start Here", name: "REAL Journey", color: "border-teal-200 bg-teal-50", labelColor: "text-teal-700" },
                  { label: "The Heart", name: "Live Layer", color: "border-gold-200 bg-gold-50", labelColor: "text-gold-700" },
                  { label: "The Rooms", name: "Deepening Pathways", color: "border-navy-100 bg-navy-50", labelColor: "text-navy-700" },
                  { label: "Conversations", name: "Shared place", color: "border-border bg-surface", labelColor: "text-teal-600" },
                ].map((item) => (
                  <div
                    key={item.label}
                    className={`flex items-center justify-between rounded-xl border px-5 py-3.5 ${item.color}`}
                  >
                    <div>
                      <p className={`text-[10px] font-semibold uppercase tracking-widest ${item.labelColor}`}>
                        {item.label}
                      </p>
                      <p className="mt-0.5 text-sm font-medium text-navy-900">{item.name}</p>
                    </div>
                    <div className="h-1.5 w-1.5 rounded-full bg-teal-400" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Container>
      </section>

      {/* What is inside — asymmetric: REAL featured, then 3-col */}
      <section className="py-20 md:py-28">
        <Container>
          <SectionHeading
            title="What is inside."
            subtitle="Four connected parts. Each one designed to support the others."
            className="mb-14 max-w-xl"
          />

          <div className="space-y-6">
            {/* REAL Journey — featured full-width */}
            <div
              className="overflow-hidden rounded-xl border border-teal-100 bg-teal-50"
              style={{ boxShadow: "var(--fc-shadow-sm)" }}
            >
              <div className="flex flex-col md:flex-row md:items-stretch">
                <div className="flex-1 p-8 md:p-10">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-teal-700">
                    Start Here
                  </p>
                  <h3 className="mb-3 font-serif text-2xl text-navy-900">REAL Journey</h3>
                  <p className="mb-4 max-w-md text-sm leading-relaxed text-[#4A5568]">
                    Every member begins with the REAL Journey — four grounded phases that build
                    self-awareness, clarity, and a way forward. You can return to it at any time.
                  </p>
                  <Link
                    href="/real-journey"
                    className="text-sm font-medium text-teal-700 underline-offset-4 transition-colors hover:text-teal-900 hover:underline"
                  >
                    Learn about REAL Journey →
                  </Link>
                </div>
                {/* IMAGE_PLACEHOLDER: Close-up of journalling or handwriting — warm, intimate, personal. */}
                <div className="flex min-h-[140px] items-center justify-center bg-teal-100/50 md:w-56 md:shrink-0">
                  <div className="font-serif text-6xl font-light tracking-[0.4em] text-teal-300">
                    REAL
                  </div>
                </div>
              </div>
            </div>

            {/* Three remaining pillars — 3-col */}
            <div className="grid gap-6 md:grid-cols-3">
              <Card className="flex flex-col gap-3 bg-gold-50 border-gold-100">
                <p className="text-xs font-semibold uppercase tracking-[0.15em] text-gold-700">
                  The Heart
                </p>
                <h3 className="font-serif text-xl text-navy-900">Live Layer</h3>
                <p className="text-sm leading-relaxed text-[#4A5568]">
                  Monthly live calls, community prompts, integration threads, and a shared space
                  with women moving through the same work.
                </p>
              </Card>

              <Card className="flex flex-col gap-3 bg-navy-50 border-navy-100">
                <p className="text-xs font-semibold uppercase tracking-[0.15em] text-navy-700">
                  The Rooms
                </p>
                <h3 className="font-serif text-xl text-navy-900">Deepening Pathways</h3>
                <p className="text-sm leading-relaxed text-[#4A5568]">
                  Once you have your foundation, The Rooms take you deeper. Growth pathway is live.
                  Transformation and Essence are coming soon.
                </p>
              </Card>

              <Card className="flex flex-col gap-3">
                <p className="text-xs font-semibold uppercase tracking-[0.15em] text-teal-600">
                  Conversations
                </p>
                <h3 className="font-serif text-xl text-navy-900">Shared place</h3>
                <p className="text-sm leading-relaxed text-[#4A5568]">
                  A feed, member reflections, and discussion threads tied to live calls and REAL
                  phases. You are not doing this alone.
                </p>
              </Card>
            </div>
          </div>
        </Container>
      </section>

      {/* What a week inside looks like */}
      <section className="border-t border-border bg-ivory py-20 md:py-28">
        <Container>
          <div className="max-w-2xl">
            <SectionHeading
              title="What a week inside looks like."
              subtitle="Not a schedule. A rhythm."
              className="mb-12"
            />
            <div className="space-y-12">
              <div className="flex gap-8">
                <div className="shrink-0 pt-0.5">
                  <span className="font-serif text-5xl font-light leading-none text-gold-400">01</span>
                </div>
                <div className="pt-2">
                  <p className="mb-2 text-sm font-semibold text-navy-900">At the start of your week</p>
                  <p className="text-sm leading-relaxed text-[#4A5568]">
                    You open your REAL Journey phase. A short lesson. A reflection prompt to carry
                    with you. Five minutes, not fifty. You move on with your day. The work begins to
                    settle underneath everything else.
                  </p>
                </div>
              </div>
              <div className="flex gap-8">
                <div className="shrink-0 pt-0.5">
                  <span className="font-serif text-5xl font-light leading-none text-gold-400">02</span>
                </div>
                <div className="pt-2">
                  <p className="mb-2 text-sm font-semibold text-navy-900">Mid-week</p>
                  <p className="text-sm leading-relaxed text-[#4A5568]">
                    A community prompt lands. You read what other women are noticing this week.
                    Maybe you write something. Maybe you just recognise yourself in someone
                    else&apos;s words. Either way, you feel less alone in what you are moving through.
                  </p>
                </div>
              </div>
              <div className="flex gap-8">
                <div className="shrink-0 pt-0.5">
                  <span className="font-serif text-5xl font-light leading-none text-gold-400">03</span>
                </div>
                <div className="pt-2">
                  <p className="mb-2 text-sm font-semibold text-navy-900">This month</p>
                  <p className="text-sm leading-relaxed text-[#4A5568]">
                    There is a live call. You are in a room with other women doing the same work. It
                    is led. It is structured. It is not a 90-minute performance — it is an hour of
                    grounded, honest conversation. You leave with something you did not have before.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </Container>
      </section>

      {/* Community emphasis — teal wash with pull-quote */}
      <section className="bg-teal-50 py-20 md:py-28">
        <Container>
          <div className="max-w-2xl">
            <div className="mb-8 h-px w-8 bg-gold-400" />
            <p className="mb-10 font-serif text-2xl leading-relaxed text-navy-900 md:text-3xl">
              Community is not a bonus.<br />
              It is <em className="text-teal-600">the point.</em>
            </p>
            <SectionHeading title="Community is the primary value." className="mb-8" />
            <div className="space-y-5 leading-relaxed text-[#4A5568]">
              <p>
                Most membership platforms treat community as a bonus. Here, it is the point.
              </p>
              <p>
                The monthly live call, the integration threads, the prompts and reflections — they
                are not extras. They are where the real work happens. Being witnessed by other women
                who are moving through the same work is one of the most powerful things this platform
                offers.
              </p>
              <p>
                This is a structured space, not a constant support channel. The founder is not
                available 24/7. The structure holds the community. That is by design.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* Bottom CTA */}
      <section className="bg-navy-950 py-20 md:py-24">
        <Container>
          <div className="max-w-xl">
            <SectionHeading
              title="Ready to join?"
              subtitle="Start where you are. The structure will hold you."
              className="mb-8"
              dark
            />
            <div className="flex flex-wrap gap-4">
              {/* STRIPE_INTEGRATION */}
              <button className="inline-flex items-center justify-center rounded-lg border border-teal-500 bg-teal-500 px-7 py-3.5 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700 hover:border-teal-700">
                Join Fresh Collective
              </button>
              <Link
                href="/real-journey"
                className="inline-flex items-center justify-center rounded-lg border border-white/30 bg-transparent px-7 py-3.5 text-base font-medium text-white transition-colors duration-200 hover:border-white/60 hover:bg-white/10"
              >
                Start with REAL Journey first
              </Link>
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  );
}
