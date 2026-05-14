import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";

export default function Home() {
  return (
    <SiteShell heroHeader>

      {/* ─── HERO ─────────────────────────────────────────────────────────── */}
      <section className="relative min-h-screen flex items-end overflow-hidden">
        {/* Ocean video */}
        <video
          className="absolute inset-0 h-full w-full object-cover"
          autoPlay
          muted
          loop
          playsInline
          aria-hidden="true"
        >
          <source src="/videos/hero-waves.mp4" type="video/mp4" />
        </video>

        {/* Cinematic overlay — heavier at bottom for text legibility */}
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(to bottom, rgba(15,27,48,0.45) 0%, rgba(15,27,48,0.30) 40%, rgba(15,27,48,0.72) 80%, rgba(15,27,48,0.90) 100%)",
          }}
        />

        <Container className="relative z-10 pb-20 pt-48 md:pb-28 md:pt-56">
          <div className="max-w-5xl">
            <p className="mb-6 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.25em] text-white/50">
              <span className="inline-block h-px w-8 shrink-0 bg-gold-400/60" aria-hidden="true" />
              Fresh Collective
            </p>

            <h1 className="mb-8 font-serif leading-[1.05] text-white">
              <span className="block text-5xl md:text-7xl lg:text-8xl">
                Exploring better ways to
              </span>
              <span
                className="block text-5xl md:text-7xl lg:text-8xl"
                style={{
                  background: "linear-gradient(90deg, #7EBDBC 0%, #D4B060 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                live, learn, create,
              </span>
              <span className="block text-5xl md:text-7xl lg:text-8xl">
                and lead.
              </span>
            </h1>

            <p className="mb-10 max-w-xl text-base leading-relaxed text-white/60 md:text-lg">
              A membership for women ready to stop managing and start moving —
              with structure, community, and depth that lasts.
            </p>

            <div className="flex flex-wrap gap-4">
              <Link
                href="/membership"
                className="inline-flex items-center justify-center rounded-lg bg-teal-500 px-8 py-3.5 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-400"
              >
                Join Fresh Collective
              </Link>
              <Link
                href="/real-journey"
                className="inline-flex items-center justify-center rounded-lg border border-white/25 px-8 py-3.5 text-sm font-medium text-white/80 backdrop-blur-sm transition-colors duration-200 hover:border-white/50 hover:text-white"
              >
                Start with REAL Journey
              </Link>
            </div>
          </div>
        </Container>
      </section>

      {/* ─── DUAL INTENT ──────────────────────────────────────────────────── */}
      <section className="bg-ivory py-24 md:py-32">
        <Container>
          <div className="grid gap-16 md:grid-cols-2 md:gap-20">
            <div>
              <div className="mb-5 h-px w-8 bg-gold-400" />
              <h2 className="mb-5 font-serif text-3xl leading-snug text-navy-900 md:text-4xl">
                A more intentional<br />way to grow.
              </h2>
              <p className="text-base leading-relaxed text-[#4A5568]">
                Most growth happens by accident — in reaction to pressure, to loss, to necessity.
                Fresh Collective offers something rarer: a structured environment where growth
                is deliberate, paced, and yours to keep.
              </p>
            </div>

            <div className="md:pt-16">
              <div className="mb-5 h-px w-8 bg-teal-400" />
              <h2 className="mb-5 font-serif text-3xl leading-snug text-navy-900 md:text-4xl">
                Environments where<br />people actually change.
              </h2>
              <p className="text-base leading-relaxed text-[#4A5568]">
                Information is abundant. What changes people is the right container — the right
                questions, at the right time, with others going through the same thing.
                That is what we have built.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* ─── ECOSYSTEM STATEMENT ──────────────────────────────────────────── */}
      <section className="border-t border-border-light bg-background py-20 md:py-24">
        <Container>
          <div className="max-w-4xl">
            <p className="font-serif text-4xl leading-tight text-navy-900 md:text-5xl md:leading-tight lg:text-6xl">
              Not a product.{" "}
              <em className="text-teal-700">An ecosystem.</em>
            </p>
            <p className="mt-6 max-w-xl text-base leading-relaxed text-[#4A5568] md:text-lg">
              One foundation, a live community layer, and deepening pathways — designed to
              work together as a connected system, not as separate courses.
            </p>
          </div>
        </Container>
      </section>

      {/* ─── FRESH IDEAS (dark teal) ──────────────────────────────────────── */}
      <section className="overflow-hidden bg-teal-900 py-24 md:py-32">
        <Container>
          <div className="grid items-center gap-16 md:grid-cols-[55%_45%] md:gap-12">

            {/* Left: heading */}
            <div>
              <h2 className="mb-8 font-serif text-5xl leading-tight text-white md:text-6xl lg:text-7xl">
                Fresh ideas need spaces to grow.
              </h2>
              <p className="mb-10 max-w-md text-base leading-relaxed text-teal-200">
                We do not believe in passive consumption. Inside Fresh Collective,
                you are always in motion — reflecting, connecting, integrating — with
                enough structure to hold you and enough space to breathe.
              </p>
              <div className="grid grid-cols-3 gap-6 border-t border-teal-700 pt-10">
                <div>
                  <div className="font-serif text-4xl font-light text-white">4</div>
                  <div className="mt-1 text-xs font-medium uppercase tracking-widest text-teal-400">Phases</div>
                </div>
                <div>
                  <div className="font-serif text-4xl font-light text-gold-300">1×</div>
                  <div className="mt-1 text-xs font-medium uppercase tracking-widest text-teal-400">Live call monthly</div>
                </div>
                <div>
                  <div className="font-serif text-4xl font-light text-teal-300">∞</div>
                  <div className="mt-1 text-xs font-medium uppercase tracking-widest text-teal-400">Your pace</div>
                </div>
              </div>
            </div>

            {/* Right: documentary artifact elements */}
            <div className="relative hidden md:block" style={{ height: "420px" }}>

              {/* Artifact 1 — bottom left, base layer */}
              <div
                className="absolute rounded-lg bg-white/95 p-5 shadow-xl"
                style={{
                  width: "220px",
                  bottom: "30px",
                  left: "0px",
                  transform: "rotate(-3deg)",
                  boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
                }}
              >
                <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-teal-700">
                  REAL Journey · Phase 1
                </div>
                <div className="mb-3 font-serif text-sm font-medium text-navy-900">Recognise</div>
                <div className="space-y-1.5">
                  <div className="h-1.5 rounded-full bg-navy-100" />
                  <div className="h-1.5 w-4/5 rounded-full bg-navy-100" />
                  <div className="h-1.5 w-3/5 rounded-full bg-navy-100" />
                </div>
                <div className="mt-4 flex gap-1">
                  <div className="h-1 flex-1 rounded-full bg-teal-500" />
                  <div className="h-1 flex-1 rounded-full bg-navy-100" />
                  <div className="h-1 flex-1 rounded-full bg-navy-100" />
                  <div className="h-1 flex-1 rounded-full bg-navy-100" />
                </div>
              </div>

              {/* Artifact 2 — centre, middle layer */}
              <div
                className="absolute rounded-lg p-5 shadow-xl"
                style={{
                  width: "230px",
                  top: "40px",
                  left: "80px",
                  background: "#F7F3ED",
                  transform: "rotate(1.5deg)",
                  boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
                }}
              >
                <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-gold-700">
                  Monthly Prompt
                </div>
                <div className="mb-3 font-serif text-sm leading-snug text-navy-900">
                  What would it feel like to stop carrying this alone?
                </div>
                <div className="space-y-1.5">
                  <div className="h-1.5 rounded-full bg-gold-200" />
                  <div className="h-1.5 w-5/6 rounded-full bg-gold-200" />
                  <div className="h-1.5 w-2/3 rounded-full bg-gold-200" />
                </div>
              </div>

              {/* Artifact 3 — top right, front layer */}
              <div
                className="absolute rounded-lg bg-navy-950 p-5 shadow-xl"
                style={{
                  width: "200px",
                  top: "10px",
                  right: "10px",
                  transform: "rotate(-1deg)",
                  boxShadow: "0 20px 60px rgba(0,0,0,0.45)",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
              >
                <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-teal-400">
                  Live Call
                </div>
                <div className="mb-1 text-sm font-medium text-white">Monthly gathering</div>
                <div className="mb-4 text-xs text-navy-400">60 min · Structured · Led</div>
                <div
                  className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[10px] font-medium text-gold-300"
                  style={{ background: "rgba(184,144,42,0.15)" }}
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-gold-400" />
                  Upcoming
                </div>
              </div>

              {/* Artifact 4 — bottom right */}
              <div
                className="absolute rounded-lg p-4 shadow-lg"
                style={{
                  width: "180px",
                  bottom: "20px",
                  right: "0px",
                  background: "rgba(255,255,255,0.12)",
                  backdropFilter: "blur(8px)",
                  border: "1px solid rgba(255,255,255,0.15)",
                  transform: "rotate(2deg)",
                }}
              >
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-teal-300">
                  Community
                </div>
                <div className="text-xs leading-relaxed text-white/70">
                  Women in the same phase, at the same time.
                </div>
              </div>
            </div>

          </div>
        </Container>
      </section>

      {/* ─── THE WAY WE FEEL ──────────────────────────────────────────────── */}
      <section className="py-24 md:py-32">
        <Container>
          <div className="mb-16 max-w-2xl">
            <h2 className="font-serif text-4xl leading-tight text-navy-900 md:text-5xl">
              The way we feel changes<br />
              what becomes possible.
            </h2>
          </div>

          <div className="grid gap-10 md:grid-cols-3">
            <div>
              <div className="mb-4 h-px w-6 bg-teal-400" />
              <h3 className="mb-3 font-serif text-lg text-navy-900">A more settled mind.</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                When you have a framework for where you are and where you are headed,
                the noise quiets. Clarity is not a luxury — it is the starting point.
              </p>
            </div>
            <div className="md:pt-8">
              <div className="mb-4 h-px w-6 bg-gold-400" />
              <h3 className="mb-3 font-serif text-lg text-navy-900">In it with others, honestly.</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Not a curated highlight reel. Real women, moving through real phases —
                with enough structure that the conversations go somewhere.
              </p>
            </div>
            <div>
              <div className="mb-4 h-px w-6 bg-navy-400" />
              <h3 className="mb-3 font-serif text-lg text-navy-900">A thread back to yourself.</h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                When life is full and loud, the REAL Journey gives you something to return to —
                a stable, consistent thread through all of it.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* ─── WHERE THE LEARNING LIVES ─────────────────────────────────────── */}
      <section className="bg-ivory py-24 md:py-32">
        <Container>
          <div className="mb-14">
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">
              The Structure
            </p>
            <h2 className="font-serif text-4xl text-navy-900 md:text-5xl">
              Where the learning lives
            </h2>
          </div>

          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {/* REAL Journey */}
            <div
              className="col-span-full rounded-xl border border-teal-100 bg-white p-8 md:col-span-2 lg:col-span-1 lg:row-span-2"
              style={{ boxShadow: "var(--fc-shadow-sm)" }}
            >
              <div
                className="mb-4 font-serif text-[6rem] font-light leading-none text-teal-100 select-none"
                aria-hidden="true"
              >
                01
              </div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-teal-700">
                Start Here
              </p>
              <h3 className="mb-3 font-serif text-2xl text-navy-900">REAL Journey</h3>
              <p className="mb-6 text-sm leading-relaxed text-[#4A5568]">
                Four phases — Recognise, Explore, Align, Lead. The foundation every member
                begins with. Bite-sized. Stabilising. Something to return to, again and again.
              </p>
              <Link
                href="/real-journey"
                className="text-sm font-medium text-teal-700 underline-offset-4 transition-colors hover:text-teal-900 hover:underline"
              >
                Learn more about REAL Journey →
              </Link>
            </div>

            {/* Live Layer */}
            <div
              className="rounded-xl border border-gold-100 bg-white p-8"
              style={{ boxShadow: "var(--fc-shadow-sm)" }}
            >
              <div
                className="mb-4 font-serif text-[6rem] font-light leading-none text-gold-100 select-none"
                aria-hidden="true"
              >
                02
              </div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-gold-700">
                The Heart
              </p>
              <h3 className="mb-3 font-serif text-xl text-navy-900">Live Layer</h3>
              <p className="mb-5 text-sm leading-relaxed text-[#4A5568]">
                Monthly live calls. Community prompts. Integration threads.
                The place where the membership comes alive.
              </p>
              <Link
                href="/membership"
                className="text-sm font-medium text-gold-700 underline-offset-4 transition-colors hover:text-gold-900 hover:underline"
              >
                Explore Membership →
              </Link>
            </div>

            {/* Deepening Pathways */}
            <div
              className="rounded-xl border border-navy-100 bg-white p-8"
              style={{ boxShadow: "var(--fc-shadow-sm)" }}
            >
              <div
                className="mb-4 font-serif text-[6rem] font-light leading-none text-navy-100 select-none"
                aria-hidden="true"
              >
                03
              </div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-navy-700">
                The Rooms
              </p>
              <h3 className="mb-3 font-serif text-xl text-navy-900">Deepening Pathways</h3>
              <p className="mb-5 text-sm leading-relaxed text-[#4A5568]">
                Growth, Transformation, Essence. Once you have your foundation,
                the pathways take you deeper — at your own pace.
              </p>
              <Link
                href="/membership"
                className="text-sm font-medium text-navy-700 underline-offset-4 transition-colors hover:text-navy-900 hover:underline"
              >
                Explore Membership →
              </Link>
            </div>
          </div>
        </Container>
      </section>

      {/* ─── WHAT GETS MADE (artifacts) ───────────────────────────────────── */}
      <section className="py-24 md:py-32">
        <Container>
          <div className="grid items-start gap-16 md:grid-cols-2 md:gap-20">

            <div className="md:sticky md:top-20">
              <p className="mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-[#718096]">
                What you get
              </p>
              <h2 className="mb-6 font-serif text-4xl leading-tight text-navy-900 md:text-5xl">
                What gets made when women have the right container.
              </h2>
              <p className="text-base leading-relaxed text-[#4A5568]">
                Not information. Not another thing to consume and forget.
                Real movement. Clarity that stays. Connections that matter.
              </p>
            </div>

            <div className="space-y-6">
              {/* Artifact items */}
              {[
                {
                  label: "Reflection",
                  heading: "A cleaner sense of what is actually true.",
                  body: "The REAL Journey is designed to interrupt the loop — to help you see what has been running in the background so you can choose something different.",
                  accent: "border-l-teal-400",
                },
                {
                  label: "Connection",
                  heading: "A community that does not require performance.",
                  body: "Live calls and integration threads create a space where showing up honestly is the norm — not the exception.",
                  accent: "border-l-gold-400",
                },
                {
                  label: "Direction",
                  heading: "A sense of what the next phase actually looks like.",
                  body: "Each pathway in The Rooms builds on your foundation and points toward something concrete — growth, transformation, or a deeper sense of essence.",
                  accent: "border-l-navy-400",
                },
                {
                  label: "Continuity",
                  heading: "Something to return to when life gets loud.",
                  body: "The structure stays. Your REAL Journey, your community, your pathways — still there when you are ready to come back.",
                  accent: "border-l-teal-300",
                },
              ].map(({ label, heading, body, accent }) => (
                <div
                  key={label}
                  className={`rounded-r-lg border-l-2 bg-background px-6 py-5 ${accent}`}
                >
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#718096]">
                    {label}
                  </p>
                  <h3 className="mb-2 font-serif text-base text-navy-900">{heading}</h3>
                  <p className="text-sm leading-relaxed text-[#4A5568]">{body}</p>
                </div>
              ))}
            </div>

          </div>
        </Container>
      </section>

      {/* ─── CONDITIONS ───────────────────────────────────────────────────── */}
      <section className="border-t border-border-light bg-ivory py-24 md:py-32">
        <Container>
          <div className="mb-14 max-w-2xl">
            <h2 className="font-serif text-4xl leading-tight text-navy-900 md:text-5xl">
              The conditions matter<br />
              <em className="text-navy-500">as much as the content.</em>
            </h2>
          </div>

          <div className="grid gap-10 md:grid-cols-3">
            <div>
              <div className="mb-5 font-serif text-5xl font-light text-teal-200 select-none">01</div>
              <h3 className="mb-3 font-serif text-lg text-navy-900">
                A pace that does not break you.
              </h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Everything inside Fresh Collective is designed to be returned to — not raced through.
                There is no urgency here. The membership holds.
              </p>
            </div>
            <div className="md:pt-8">
              <div className="mb-5 font-serif text-5xl font-light text-gold-200 select-none">02</div>
              <h3 className="mb-3 font-serif text-lg text-navy-900">
                People building the same things.
              </h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                You are not dropped into a general community. You are alongside women working
                through the same phases, the same questions, the same moments.
              </p>
            </div>
            <div>
              <div className="mb-5 font-serif text-5xl font-light text-navy-200 select-none">03</div>
              <h3 className="mb-3 font-serif text-lg text-navy-900">
                A leader who has been there.
              </h3>
              <p className="text-sm leading-relaxed text-[#4A5568]">
                Fresh Collective was built from the inside out — by someone who has moved through
                these phases herself, not just observed them.
              </p>
            </div>
          </div>
        </Container>
      </section>

      {/* ─── QUESTIONS ────────────────────────────────────────────────────── */}
      <section className="py-24 md:py-32">
        <Container>
          <div className="grid gap-16 md:grid-cols-[40%_60%] md:gap-20">
            <div>
              <h2 className="font-serif text-3xl leading-tight text-navy-900 md:text-4xl">
                Good questions deserve honest answers.
              </h2>
            </div>

            <div className="space-y-8">
              {[
                {
                  q: "What if I am already overwhelmed?",
                  a: "That is exactly the right time to start. The REAL Journey is designed for people who are already full — it is structured to be light enough to actually do, even when everything else is heavy.",
                },
                {
                  q: "Is this another online course I will not finish?",
                  a: "Fresh Collective is not built around consumption. It is built around consistency — short touchpoints, a live layer, and a community that keeps you moving even when motivation is low.",
                },
                {
                  q: "What is the difference between the REAL Journey and full membership?",
                  a: "The REAL Journey is the foundation — four phases, your own pace. Full membership adds the live layer (monthly calls, community prompts) and access to The Rooms. Both are meaningful starting points.",
                },
                {
                  q: "How much time do I need?",
                  a: "The REAL Journey is designed around bite-sized sessions. The monthly live call is 60 minutes. Most members find 30–60 minutes a week is enough to stay connected and moving.",
                },
              ].map(({ q, a }) => (
                <div key={q} className="border-t border-border pt-8">
                  <h3 className="mb-3 font-serif text-lg text-navy-900">{q}</h3>
                  <p className="text-sm leading-relaxed text-[#4A5568]">{a}</p>
                </div>
              ))}
            </div>
          </div>
        </Container>
      </section>

      {/* ─── FINAL CTA ────────────────────────────────────────────────────── */}
      <section className="bg-navy-950 py-32 md:py-40">
        <Container>
          <div className="mx-auto max-w-3xl text-center">
            <div className="mx-auto mb-10 h-px w-10 bg-gold-500/40" />
            <h2 className="mb-8 font-serif text-5xl leading-tight text-white md:text-6xl lg:text-7xl">
              Find your collective.{" "}
              <em
                style={{
                  background: "linear-gradient(90deg, #7EBDBC 0%, #D4B060 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                  fontStyle: "italic",
                }}
              >
                Or build one.
              </em>
            </h2>
            <p className="mx-auto mb-10 max-w-lg text-base leading-relaxed text-navy-300 md:text-lg">
              Two ways in. No wrong starting point. Start with the foundation,
              or step into the full membership from day one.
            </p>
            <div className="flex flex-wrap justify-center gap-4">
              <Link
                href="/membership"
                className="inline-flex items-center justify-center rounded-lg bg-teal-500 px-8 py-4 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-400"
              >
                Join Fresh Collective
              </Link>
              <Link
                href="/real-journey"
                className="inline-flex items-center justify-center rounded-lg border border-white/20 px-8 py-4 text-sm font-medium text-navy-300 transition-colors duration-200 hover:border-white/40 hover:text-white"
              >
                Start with REAL Journey
              </Link>
            </div>
            <div className="mx-auto mt-10 h-px w-10 bg-gold-500/40" />
          </div>
        </Container>
      </section>

    </SiteShell>
  );
}
