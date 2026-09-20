import type { Metadata } from "next";
import "./globals.css";
import { FreshProviders } from "@/components/platform/FreshProviders";
import { BrandProvider } from '@/components/brand/BrandProvider'
import { getBrandOverrides } from '@/lib/serverApi'

export const metadata: Metadata = {
  title: "Fresh Collective",
  description: "A membership-based transformation platform for women.",
};

// Icons are resolved by Next.js from the files beside this one —
// ``favicon.ico``, ``icon.png`` and ``apple-icon.png`` — because the
// framework reads them from the filesystem at build time and cannot
// ask the database what the brand currently is. They are not a second
// design: ``backend/scripts/compose_app_icon.py`` generates all three
// from the same composition as the ``favicon_app_icon`` brand role,
// and a test regenerates and compares them. An admin override of that
// role therefore changes every runtime surface immediately and the
// browser tab at the next deploy; the two cannot drift apart in what
// they depict, only in when they update.

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Brand artwork is resolved once, here, for the whole request. Each
  // header, footer and sidebar then reads from context instead of
  // asking for itself — one lookup rather than one per chrome element,
  // and no way for two of them to disagree. The fetch is public and
  // revalidating rather than session-bound, so pages that render
  // statically today stay static.
  const brandOverrides = await getBrandOverrides()
  return (
    <html lang="en" className="h-full antialiased" data-scroll-behavior="smooth">
      <body className="flex min-h-full flex-col">
        <BrandProvider overrides={brandOverrides}>
          <FreshProviders>{children}</FreshProviders>
        </BrandProvider>
      </body>
    </html>
  );
}
