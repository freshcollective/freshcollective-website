import Link from "next/link";
import Container from "./Container";

export default function PublicHeader() {
  return (
    <header
      className="border-b border-border bg-surface py-5"
      style={{ borderTop: "2px solid var(--color-gold-500)" }}
    >
      <Container className="flex items-center justify-between">
        <Link
          href="/"
          className="font-serif text-xl tracking-wide text-navy-900 transition-colors hover:text-navy-700"
        >
          Fresh Collective
        </Link>

        <nav aria-label="Main navigation" className="hidden items-center gap-8 md:flex">
          <Link
            href="/about"
            className="text-sm text-[#4A5568] transition-colors hover:text-navy-900"
          >
            About
          </Link>
          <Link
            href="/real-journey"
            className="text-sm text-[#4A5568] transition-colors hover:text-navy-900"
          >
            REAL Journey
          </Link>
          <Link
            href="/membership"
            className="text-sm text-[#4A5568] transition-colors hover:text-navy-900"
          >
            Membership
          </Link>
        </nav>

        <div className="flex items-center gap-4">
          <Link
            href="/login"
            className="hidden text-sm text-[#4A5568] transition-colors hover:text-navy-900 md:block"
          >
            Log in
          </Link>
          <Link
            href="/signup"
            className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-4 py-2 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-700"
          >
            Join
          </Link>
        </div>
      </Container>
    </header>
  );
}
