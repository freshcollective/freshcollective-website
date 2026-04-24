import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";
import Card from "@/components/ui/Card";
import SectionHeading from "@/components/ui/SectionHeading";

const pillars = [
  {
    label: "Start Here",
    name: "REAL Journey",
    description:
      "Every member begins with the REAL Journey — four grounded phases that build self-awareness, clarity, and a way forward. You can return to it at any time.",
    href: "/real-journey",
  },
  {
    label: "The Heart",
    name: "Live Layer",
    description:
      "Monthly live calls, community prompts, integration threads, and a shared space with women moving through the same work. This is where the membership comes alive.",
    href: null,
  },
  {
    label: "The Rooms",
    name: "Deepening Pathways",
    description:
      "Once you have your foundation, The Rooms take you deeper. Growth pathway is live. Transformation and Essence are coming soon.",
    href: null,
  },
  {
    label: "Community",
    name: "Shared space",
    description:
      "A feed, member reflections, and discussion threads tied to live calls and REAL phases. You are not doing this alone.",
    href: null,
  },
];

export default function MembershipPage() {
  return (
    <SiteShell>
      {/* Hero */}
      <section className="border-b border-border py-20 md:py-28">
        <Container>
          <div className="max-w-2xl">
            <p className="mb-5 text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">
              Full membership
            </p>
            <h1 className="mb-6 font-serif text-4xl leading-tight text-navy-900 md:text-5xl">
              Everything you need to move from survival into expansion.
            </h1>
            <p className="mb-10 text-lg leading-relaxed text-[#4A5568]">
              Fresh Collective membership gives you the full structure: a grounded foundation, a live
              community layer, deepening pathways, and the people who make it real.
            </p>
            {/* STRIPE_INTEGRATION */}
            <button className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-6 py-3 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700">
              Join Fresh Collective
            </button>
          </div>
        </Container>
      </section>

      {/* What is inside */}
      <section className="py-20 md:py-28">
        <Container>
          <SectionHeading
            title="What is inside."
            subtitle="Not a course library. A connected system — designed so that each part supports the others."
            className="mb-14 max-w-xl"
          />
          <div className="grid gap-6 md:grid-cols-2">
            {pillars.map((pillar) => (
              <Card key={pillar.label} className="flex flex-col gap-3">
                <p className="text-xs font-semibold uppercase tracking-[0.15em] text-teal-600">
                  {pillar.label}
                </p>
                <h3 className="font-serif text-xl text-navy-900">{pillar.name}</h3>
                <p className="text-sm leading-relaxed text-[#4A5568]">{pillar.description}</p>
                {pillar.href && (
                  <Link
                    href={pillar.href}
                    className="mt-1 text-sm font-medium text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
                  >
                    Learn more →
                  </Link>
                )}
              </Card>
            ))}
          </div>
        </Container>
      </section>

      {/* Community emphasis */}
      <section className="border-t border-border py-20 md:py-28">
        <Container>
          <div className="max-w-2xl">
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
      <section className="border-t border-border bg-navy-50 py-20 md:py-24">
        <Container>
          <div className="max-w-xl">
            <SectionHeading
              title="Ready to join?"
              subtitle="Start where you are. The structure will hold you."
              className="mb-8"
            />
            <div className="flex flex-wrap gap-4">
              {/* STRIPE_INTEGRATION */}
              <button className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-6 py-3 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700">
                Join Fresh Collective
              </button>
              <Link
                href="/real-journey"
                className="inline-flex items-center justify-center rounded-lg border border-navy-300 bg-transparent px-6 py-3 text-base font-medium text-navy-900 transition-colors duration-200 hover:border-navy-500 hover:bg-navy-50"
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
