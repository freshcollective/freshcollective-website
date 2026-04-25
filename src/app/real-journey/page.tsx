import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";
import Card from "@/components/ui/Card";
import SectionHeading from "@/components/ui/SectionHeading";

const phases = [
  {
    letter: "R",
    name: "Recognise",
    description:
      "Seeing clearly what is true right now. Not what you think should be true, or what you want to be true — what is actually true. This is where honest self-awareness begins.",
    badgeBg: "bg-teal-100",
    badgeText: "text-teal-700",
  },
  {
    letter: "E",
    name: "Explore",
    description:
      "Getting curious about your patterns, your needs, and your desires. Exploring without judgement. Learning to see yourself with kindness rather than criticism.",
    badgeBg: "bg-gold-100",
    badgeText: "text-gold-700",
  },
  {
    letter: "A",
    name: "Align",
    description:
      "Connecting with your values and what genuinely matters to you. Building the internal compass that guides decisions from the inside out.",
    badgeBg: "bg-navy-100",
    badgeText: "text-navy-700",
  },
  {
    letter: "L",
    name: "Lead",
    description:
      "Moving forward from a grounded place. Not leading others — leading yourself. Taking one clear, sustainable step at a time.",
    badgeBg: "bg-teal-100",
    badgeText: "text-teal-700",
  },
];

export default function REALJourneyPage() {
  return (
    <SiteShell>
      {/* Hero — dark navy, premium feel */}
      <section className="bg-navy-950 py-20 md:py-32">
        <Container>
          <div className="max-w-2xl">
            <p className="mb-5 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-teal-400">
              <span className="inline-block h-px w-6 shrink-0 bg-gold-500" aria-hidden="true" />
              Where it all begins
            </p>
            <h1 className="mb-6 font-serif text-5xl leading-tight text-white md:text-6xl">
              The <em className="text-gold-400">REAL</em> Journey
            </h1>
            <p className="mb-10 text-lg leading-relaxed text-navy-300">
              A structured, grounded starting point. Four phases designed to help you see{" "}
              <em>clearly</em>, get curious, align with what matters, and move forward — at your own pace.
            </p>
            <div className="flex flex-wrap gap-4">
              {/* STRIPE_INTEGRATION */}
              <button className="inline-flex items-center justify-center rounded-lg border border-teal-500 bg-teal-500 px-7 py-3.5 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700 hover:border-teal-700">
                Buy REAL Journey
              </button>
              <Link
                href="/membership"
                className="inline-flex items-center justify-center rounded-lg border border-white/30 bg-transparent px-7 py-3.5 text-base font-medium text-white transition-colors duration-200 hover:border-white/60 hover:bg-white/10"
              >
                Join Membership (includes REAL)
              </Link>
            </div>
          </div>
        </Container>
      </section>

      {/* The four phases — very light teal wash */}
      <section className="bg-teal-50 py-20 md:py-28">
        <Container>
          <SectionHeading
            title="The four phases."
            subtitle="Each phase builds on the last. You can move at your own pace — and return to any phase at any time."
            className="mb-6 max-w-xl"
          />
          {/* What to expect when you start */}
          <p className="mb-12 max-w-xl text-sm leading-relaxed text-[#4A5568] md:text-base">
            You do not need to be ready to start. The first phase asks only one thing: honesty.
            From there, the journey builds at a pace your nervous system can hold. Most women find
            the beginning easier than they expected — and more meaningful than they anticipated.
          </p>
          <div className="grid gap-6 md:grid-cols-2">
            {phases.map((phase) => (
              <Card key={phase.letter} className="flex gap-5">
                <div className="shrink-0">
                  <span
                    className={`flex h-14 w-14 items-center justify-center rounded-full font-serif text-2xl font-medium ${phase.badgeBg} ${phase.badgeText}`}
                  >
                    {phase.letter}
                  </span>
                </div>
                <div>
                  <h3 className="mb-2 font-serif text-xl text-navy-900">{phase.name}</h3>
                  <p className="text-sm leading-relaxed text-[#4A5568]">{phase.description}</p>
                </div>
              </Card>
            ))}
          </div>
        </Container>
      </section>

      {/* Editorial pull — grounded moment between sections */}
      <section className="border-t border-border bg-ivory py-16 md:py-20">
        <Container>
          <div className="mx-auto max-w-2xl text-center">
            <div className="mx-auto mb-6 h-px w-8 bg-gold-400" />
            <p className="font-serif text-2xl leading-relaxed text-navy-900 md:text-3xl">
              You do not need to have it figured out.<br />
              You just need to be willing to <em className="text-teal-600">look.</em>
            </p>
            <div className="mx-auto mt-6 h-px w-8 bg-gold-400" />
          </div>
        </Container>
      </section>

      {/* What you get / who it's for — white */}
      <section className="border-t border-border py-20 md:py-28">
        <Container>
          <div className="grid gap-14 md:grid-cols-2 md:gap-20">
            <div>
              <SectionHeading title="What you get." className="mb-8" />
              <ul className="space-y-4 text-sm leading-relaxed text-[#4A5568]">
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-teal-500">—</span>
                  Bite-sized lessons you can move through in minutes, not hours.
                </li>
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-teal-500">—</span>
                  Reflection prompts to help you move from thinking to integration.
                </li>
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-teal-500">—</span>
                  One clear integration action per phase.
                </li>
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-teal-500">—</span>
                  Simple progress tracking so you always know where you are.
                </li>
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-teal-500">—</span>
                  The ability to return to any phase at any time.
                </li>
              </ul>
            </div>
            <div>
              <SectionHeading title="Who it is for." className="mb-8" />
              <ul className="space-y-4 text-sm leading-relaxed text-[#4A5568]">
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-gold-500">—</span>
                  Women who are ready to stop running on survival mode.
                </li>
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-gold-500">—</span>
                  Women who have done the work but want something that actually sticks.
                </li>
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-gold-500">—</span>
                  Women who need structure without pressure.
                </li>
                <li className="flex gap-3">
                  <span className="mt-0.5 shrink-0 font-medium text-gold-500">—</span>
                  Women who want to move forward — practically, not just emotionally.
                </li>
              </ul>
            </div>
          </div>
        </Container>
      </section>

      {/* Bottom CTA — dark navy */}
      <section className="bg-navy-950 py-20 md:py-24">
        <Container>
          <div className="max-w-xl">
            <SectionHeading
              title="Ready to begin?"
              subtitle="Start with REAL Journey as a standalone, or join the full membership for everything."
              className="mb-8"
              dark
            />
            <div className="flex flex-wrap gap-4">
              {/* STRIPE_INTEGRATION */}
              <button className="inline-flex items-center justify-center rounded-lg border border-teal-500 bg-teal-500 px-7 py-3.5 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700 hover:border-teal-700">
                Buy REAL Journey
              </button>
              <Link
                href="/membership"
                className="inline-flex items-center justify-center rounded-lg border border-white/30 bg-transparent px-7 py-3.5 text-base font-medium text-white transition-colors duration-200 hover:border-white/60 hover:bg-white/10"
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
