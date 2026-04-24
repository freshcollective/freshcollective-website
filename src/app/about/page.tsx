import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";
import SectionHeading from "@/components/ui/SectionHeading";

export default function AboutPage() {
  return (
    <SiteShell>
      {/* Hero */}
      <section className="border-b border-border py-20 md:py-28">
        <Container>
          <div className="max-w-2xl">
            <p className="mb-5 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">
              <span className="inline-block h-px w-6 shrink-0 bg-gold-500" aria-hidden="true" />
              About Fresh Collective
            </p>
            <h1 className="mb-6 font-serif text-4xl leading-tight text-navy-900 md:text-5xl">
              Built on the belief that sustainable change is{" "}
              <em className="text-teal-600">quiet.</em>
            </h1>
            <p className="text-lg leading-relaxed text-[#4A5568]">
              Fresh Collective exists for women who are done with quick fixes and ready for something
              that actually holds.
            </p>
          </div>
        </Container>
      </section>

      {/* Why this platform exists — teal wash */}
      <section className="bg-teal-50 py-20 md:py-28">
        <Container>
          <div className="max-w-2xl">
            <SectionHeading title="Why this platform exists." className="mb-10" />
            <div className="space-y-6 leading-relaxed text-[#4A5568]">
              <p>
                Most transformation programs are built for speed. They promise a lot, deliver
                intensity, and leave you on your own when the energy fades.
              </p>
              <p>
                Fresh Collective is built differently. It is designed for integration — for change
                that your nervous system can actually hold, that fits inside a real life, and that
                deepens over time rather than burning out.
              </p>
              <p>
                This is not a place to consume content. It is a place to practise living
                differently.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* Foundations — white with left-border accents */}
      <section className="py-20 md:py-28">
        <Container>
          <SectionHeading
            title="What it is built on."
            subtitle="Every part of Fresh Collective is grounded in the same foundations."
            className="mb-14 max-w-xl"
          />
          <div className="grid max-w-3xl gap-8 md:grid-cols-2">
            <div className="border-l-2 border-teal-200 pl-5">
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-teal-600">
                Nervous system safety
              </p>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Real change does not happen under pressure. Everything here is designed to feel
                manageable — short, grounded, and accessible even on a hard day.
              </p>
            </div>
            <div className="border-l-2 border-teal-200 pl-5">
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-teal-600">
                Personal leadership
              </p>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Not leadership as performance. Leadership as self-knowing. Moving from reactive to
                intentional, from survival to expansion.
              </p>
            </div>
            <div className="border-l-2 border-gold-300 pl-5">
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-gold-700">
                Community
              </p>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Being witnessed by other women who are doing the same work is part of the work. The
                community is not an add-on. It is one of the most important things in the platform.
              </p>
            </div>
            <div className="border-l-2 border-gold-300 pl-5">
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-gold-700">
                Practical integration
              </p>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Insight without application does not change anything. Every lesson, prompt, and live
                moment is designed to land in your actual week.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* CTA — warm gold wash */}
      <section className="bg-gold-50 py-20 md:py-24">
        <Container>
          <div className="max-w-xl">
            <SectionHeading
              title="Ready to begin?"
              subtitle="Start with the REAL Journey or explore full membership."
              className="mb-8"
            />
            <div className="flex flex-wrap gap-4">
              <Link
                href="/real-journey"
                className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-6 py-3 text-base font-medium text-white transition-colors duration-200 hover:bg-teal-700"
              >
                Start with REAL Journey
              </Link>
              <Link
                href="/membership"
                className="inline-flex items-center justify-center rounded-lg border border-navy-300 bg-transparent px-6 py-3 text-base font-medium text-navy-900 transition-colors duration-200 hover:border-navy-500 hover:bg-white"
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
