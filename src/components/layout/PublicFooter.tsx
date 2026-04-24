import Container from "./Container";

export default function PublicFooter() {
  return (
    <footer className="border-t border-border py-8">
      <Container>
        <p className="text-center text-sm text-[#718096]">
          © {new Date().getFullYear()} Fresh Collective. All rights reserved.
        </p>
      </Container>
    </footer>
  );
}
