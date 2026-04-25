import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";
import Card from "@/components/ui/Card";
import SectionHeading from "@/components/ui/SectionHeading";

const pillars = [
  {
    label: "Start Here",
    labelClass: "text-teal-700",
    name: "REAL Journey",
    description:
      "Every member begins with the REAL Journey — four grounded phases that build self-awareness, clarity, and a way forward. You can return to it at any time.",
    href: "/real-journey",
    cardClass: "bg-teal-50 border-teal-100",
    linkClass: "text-teal-700 hover:text-teal-900",
  },
  {
    label: "The Heart",
    labelClass: "text-gold-700",
    name: "Live Layer",
    description:
      "Monthly live calls, community prompts, integration threads, and a shared space with women moving through the same work. This is where the membership comes alive.",
    href: null,
    cardClass: "bg-gold-50 border-gold-100",
    linkClass: "",
  },
  {
    label: "The Rooms",
    labelClass: "text-navy-700",
    name: "Deepening Pathways",
    description:
      "Once you have your foundation, The Rooms take you deeper. Growth pathway is live. Transformation and Essence are coming soon.",
    href: null,
    cardClass: "bg-navy-50 border-navy-100",
    linkClass: "",
  },
  {
    label: "Community",
    labelClass: "text-teal-600",
    name: "Shared space",
    description:
      "A feed, member reflections, and discussion threads tied to live calls and REAL phases. You are not doing this alone.",
    href: null,
    cardClass: "",
    linkClass: "",
  },
];

export default function MembershipPage() {
  return (
    <SiteShell>
      {/* Hero */}
      <section className="border-b border-border py-20 md:py-28">
        <Container>
          <div className="max-w-2xl">
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
        </Container>
      </section>

      {/* What is inside — four tinted pillar cards */}
      <section className="py-20 md:py-28">
        <Container>
          <SectionHeading
            title="What is inside."
            subtitle="Four connected parts. Each one designed to support the others."
            className="mb-14 max-w-xl"
          />
          <div className="grid gap-6 md:grid-cols-2">
            {pillars.map((pillar) => (
              <Card key={pillar.label} className={`flex flex-col gap-3 ${pillar.cardClass}`}>
                <p className={`text-xs font-semibold uppercase tracking-[0.15em] ${pillar.labelClass}`}>
                  {pillar.label}
                </p>
                <h3 className="font-serif text-xl text-navy-900">{pillar.name}</h3>
                <p className="text-sm leading-relaxed text-[#4A5568]">{pillar.description}</p>
                {pillar.href && (
                  <Link
                    href={pillar.href}
                    className={`mt-1 text-sm font-medium underline-offset-4 transition-colors hover:underline ${pillar.linkClass}`}
                  >
                    Learn more →
                  </Link>
                )}
              </Card>
            ))}
          </div>
        </Container>
      </section>

      {/* What a week inside looks like */}
      <section className="border-t border-border py-20 md:py-28">
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
                    settle quietly underneath everything else.
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
                    Maybe you write something. Maybe you just recognise yourself in someone else&apos;s
                    words. Either way, you feel less alone in what you are moving through.
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

      {/* Bottom CTA — dark navy */}
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
