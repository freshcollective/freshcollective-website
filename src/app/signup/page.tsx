import Link from "next/link";
import SiteShell from "@/components/layout/SiteShell";
import Container from "@/components/layout/Container";
import Button from "@/components/ui/Button";

export default function SignUpPage() {
  return (
    <SiteShell>
      <section className="relative flex min-h-[80vh] items-center overflow-hidden py-20">
        {/* Background: ivory left, navy-950 right */}
        <div className="absolute inset-y-0 left-0 w-1/2 bg-ivory" aria-hidden="true" />
        <div className="absolute inset-y-0 right-0 w-1/2 bg-navy-950" aria-hidden="true" />

        <Container className="relative z-10">
          <div className="flex items-center justify-center">
            <div
              className="w-full max-w-sm rounded-xl border border-border bg-surface p-8 md:p-10"
              style={{ boxShadow: "var(--fc-shadow-md)" }}
            >
              <div className="mb-8">
                <div className="mb-4 h-px w-6 bg-gold-500" />
                <h1 className="mb-2 font-serif text-3xl text-navy-900">Create your account.</h1>
                <p className="text-sm text-[#718096]">
                  Already a member?{" "}
                  <Link
                    href="/login"
                    className="text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
                  >
                    Log in
                  </Link>
                </p>
              </div>

              {/* SUPABASE_AUTH */}
              {/* STRIPE_INTEGRATION */}
              <form className="space-y-5">
                <div>
                  <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-navy-900">
                    Full name
                  </label>
                  <input
                    id="name"
                    type="text"
                    autoComplete="name"
                    placeholder="Your name"
                    className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                  />
                </div>
                <div>
                  <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-navy-900">
                    Email address
                  </label>
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                  />
                </div>
                <div>
                  <label
                    htmlFor="password"
                    className="mb-1.5 block text-sm font-medium text-navy-900"
                  >
                    Password
                  </label>
                  <input
                    id="password"
                    type="password"
                    autoComplete="new-password"
                    placeholder="Choose a strong password"
                    className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                  />
                </div>
                <Button type="submit" variant="primary" size="md" className="w-full">
                  Create account
                </Button>
              </form>
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  );
}
