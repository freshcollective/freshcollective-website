import Container from "./Container";

export default function PublicHeader() {
  return (
    <header className="border-b border-border bg-surface py-5">
      <Container className="flex items-center justify-between">
        <span className="font-serif text-xl tracking-wide text-navy-900">
          Fresh Collective
        </span>
        <nav aria-label="Main navigation">
          {/* Navigation links added in Phase 2 */}
        </nav>
      </Container>
    </header>
  );
}
