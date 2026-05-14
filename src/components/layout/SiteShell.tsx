import { ReactNode } from "react";
import PublicHeader from "./PublicHeader";
import PublicFooter from "./PublicFooter";

export default function SiteShell({
  children,
  heroHeader = false,
}: {
  children: ReactNode;
  heroHeader?: boolean;
}) {
  if (heroHeader) {
    return (
      <div className="relative">
        <PublicHeader overlay />
        <main className="flex-1">{children}</main>
        <PublicFooter />
      </div>
    );
  }

  return (
    <>
      <PublicHeader />
      <main className="flex-1">{children}</main>
      <PublicFooter />
    </>
  );
}
