import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";

export default function Home() {
  return (
    <SiteShell>
      <section className="flex min-h-[72vh] items-center py-20 md:py-28">
        <Container>
          <div className="max-w-xl">
            <p className="mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">
              Coming soon
            </p>
            <h1 className="mb-5 font-serif text-4xl text-navy-900 md:text-5xl lg:text-6xl">
              Fresh Collective
            </h1>
            <p className="text-base leading-relaxed text-[#4A5568] md:text-lg">
              A membership platform for women moving from survival into expansion that lasts.
            </p>
          </div>
        </Container>
      </section>
    </SiteShell>
  );
}
