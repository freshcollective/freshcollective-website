import Link from "next/link";
import Container from "./Container";

export default function PublicFooter() {
  return (
    <footer className="bg-navy-950 py-14">
      <Container>
        <div className="flex flex-col gap-10 md:flex-row md:items-start md:justify-between">
          <div className="max-w-xs">
            <span className="font-serif text-xl tracking-wide text-white">Fresh Collective</span>
            <p className="mt-3 text-sm leading-relaxed text-navy-300">
              A structured transformation membership for women moving from survival into expansion
              that lasts.
            </p>
          </div>

          <nav aria-label="Footer navigation" className="flex flex-wrap gap-x-10 gap-y-3">
            <Link
              href="/about"
              className="text-sm text-navy-300 transition-colors hover:text-white"
            >
              About
            </Link>
            <Link
              href="/real-journey"
              className="text-sm text-navy-300 transition-colors hover:text-white"
            >
              REAL Journey
            </Link>
            <Link
              href="/membership"
              className="text-sm text-navy-300 transition-colors hover:text-white"
            >
              Membership
            </Link>
            <Link
              href="/login"
              className="text-sm text-navy-300 transition-colors hover:text-white"
            >
              Log in
            </Link>
            <Link
              href="/signup"
              className="text-sm text-teal-400 transition-colors hover:text-teal-200"
            >
              Join
            </Link>
          </nav>
        </div>

        <div
          className="mt-12 pt-8"
          style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }}
        >
          <p className="text-center text-xs text-navy-300" style={{ opacity: 0.6 }}>
            © {new Date().getFullYear()} Fresh Collective. All rights reserved.
          </p>
        </div>
      </Container>
    </footer>
  );
}
